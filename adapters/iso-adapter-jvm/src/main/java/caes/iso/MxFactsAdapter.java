package caes.iso;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.w3c.dom.Attr;
import org.w3c.dom.Element;
import org.w3c.dom.NamedNodeMap;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

import com.prowidesoftware.swift.model.mx.AbstractMX;
import com.prowidesoftware.swift.model.mx.AppHdr;

/**
 * P4.3 — MX facts: XML stdin -> CA_ES_SWIFT_MX_FACTS_V1 stdout.
 *
 * Parseo via Prowide (AbstractMX.parse, autodeteccion por namespace);
 * facts = walk DOM del modelo marshalleado (mx.element()) + AppHdr.
 * model_path = local-names; evidence_locator = path indexado
 * determinista. PARSE_OK significa solo parsing: nunca SCHEMA_VALID /
 * NETWORK_VALID / SWIFT_VALID.
 *
 * Seguridad: la via de parseo Prowide usa SafeXmlUtils (DTD off,
 * external entities off, secure processing, limites de entidad).
 * Cap de input; XML crudo nunca a stderr.
 *
 * Exit codes: 0 OK, 2 PARSE_ERROR, 3 UNSUPPORTED_MESSAGE_TYPE,
 * 4 ADAPTER_ERROR.
 */
public final class MxFactsAdapter {

    static final String SCHEMA_VERSION = "CA_ES_SWIFT_MX_FACTS_V1";
    static final String ADAPTER_VERSION = "0.2.0";
    static final String LIBRARY = "prowide-iso20022";
    static final String LIBRARY_VERSION = "SRU2025-10.3.10";
    static final String STANDARD_FAMILY = "ISO20022";
    static final String STANDARD_RELEASE = "SRU2025";
    static final String RELEASE_STATE_AS_OF = "2026-09-17";

    static final int MAX_INPUT_BYTES = 8 * 1024 * 1024;

    private static final Set<String> SUPPORTED = Set.of(
            "seev.031.001.15", "seev.031.002.15",
            "seev.033.001.13", "seev.033.002.13",
            "seev.034.001.15", "seev.034.002.15",
            "seev.036.001.16", "seev.036.002.16",
            "seev.050.001.01", "seev.050.001.02",
            "seev.050.001.03", "seev.051.001.01",
            "seev.051.001.02", "seev.052.001.01",
            "seev.052.001.02", "seev.052.001.03",
            "seev.053.001.01", "seev.053.001.02",
            "seev.053.001.03",
            "semt.002.001.12", "semt.002.002.11",
            "camt.053.001.13", "camt.054.001.13",
            // P17 sese.023/024/025 — todas las versiones del pin
            // SRU2025 (tracks .001 y .002)
            "sese.023.001.01", "sese.023.001.02", "sese.023.001.03",
            "sese.023.001.04", "sese.023.001.05", "sese.023.001.06",
            "sese.023.001.07", "sese.023.001.08", "sese.023.001.09",
            "sese.023.001.10", "sese.023.001.11",
            "sese.023.002.01", "sese.023.002.02", "sese.023.002.03",
            "sese.023.002.04", "sese.023.002.05", "sese.023.002.06",
            "sese.023.002.07", "sese.023.002.08", "sese.023.002.09",
            "sese.023.002.10", "sese.023.002.11",
            "sese.024.001.01", "sese.024.001.02", "sese.024.001.03",
            "sese.024.001.04", "sese.024.001.05", "sese.024.001.06",
            "sese.024.001.07", "sese.024.001.08", "sese.024.001.09",
            "sese.024.001.10", "sese.024.001.11", "sese.024.001.12",
            "sese.024.001.13",
            "sese.024.002.01", "sese.024.002.02", "sese.024.002.03",
            "sese.024.002.04", "sese.024.002.05", "sese.024.002.06",
            "sese.024.002.07", "sese.024.002.08", "sese.024.002.09",
            "sese.024.002.10", "sese.024.002.11", "sese.024.002.12",
            "sese.025.001.01", "sese.025.001.02", "sese.025.001.03",
            "sese.025.001.04", "sese.025.001.05", "sese.025.001.06",
            "sese.025.001.07", "sese.025.001.08", "sese.025.001.09",
            "sese.025.001.10", "sese.025.001.11", "sese.025.001.12",
            "sese.025.002.01", "sese.025.002.02", "sese.025.002.03",
            "sese.025.002.04", "sese.025.002.05", "sese.025.002.06",
            "sese.025.002.07", "sese.025.002.08", "sese.025.002.09",
            "sese.025.002.10", "sese.025.002.11");

    private MxFactsAdapter() {
    }

    public static IsoAdapter.Result mainResult() {
        byte[] raw;
        try {
            raw = System.in.readAllBytes();
        } catch (IOException e) {
            return new IsoAdapter.Result(IsoAdapter.EXIT_ADAPTER_ERROR,
                    envelope(null, null, "ADAPTER_ERROR",
                             e.getClass().getSimpleName(), List.of()));
        }
        return run(raw);
    }

    /** XML raw -> doc del contrato. Pura/testeable. */
    public static IsoAdapter.Result run(byte[] raw) {
        String sha = sha256hex(raw);
        if (raw.length == 0) {
            return new IsoAdapter.Result(IsoAdapter.EXIT_PARSE_ERROR,
                    envelope(sha, null, "PARSE_ERROR",
                             "EMPTY_INPUT", List.of()));
        }
        if (raw.length > MAX_INPUT_BYTES) {
            return new IsoAdapter.Result(IsoAdapter.EXIT_PARSE_ERROR,
                    envelope(sha, null, "PARSE_ERROR",
                             "INPUT_TOO_LARGE", List.of()));
        }
        String xml = new String(raw, StandardCharsets.UTF_8);
        AbstractMX mx;
        try {
            mx = AbstractMX.parse(xml);
        } catch (Throwable t) {
            return new IsoAdapter.Result(IsoAdapter.EXIT_PARSE_ERROR,
                    envelope(sha, null, "PARSE_ERROR",
                             t.getClass().getSimpleName(), List.of()));
        }
        if (mx == null || mx.getMxId() == null) {
            return new IsoAdapter.Result(IsoAdapter.EXIT_PARSE_ERROR,
                    envelope(sha, null, "PARSE_ERROR",
                             "UNRECOGNIZED_MESSAGE", List.of()));
        }
        String mid = mx.getMxId().id();
        if (!SUPPORTED.contains(mid)) {
            return new IsoAdapter.Result(IsoAdapter.EXIT_UNSUPPORTED,
                    envelope(sha, mid, "UNSUPPORTED_MESSAGE_TYPE",
                             mid, List.of()));
        }
        List<Map<String, Object>> facts;
        try {
            facts = extractFacts(mx, mid, sha);
        } catch (Throwable t) {
            return new IsoAdapter.Result(IsoAdapter.EXIT_ADAPTER_ERROR,
                    envelope(sha, mid, "ADAPTER_ERROR",
                             t.getClass().getSimpleName(), List.of()));
        }
        return new IsoAdapter.Result(IsoAdapter.EXIT_OK,
                envelope(sha, mid, "PARSE_OK", null, facts));
    }

    private static Map<String, Object> envelope(
            String sha, String mid, String parseStatus,
            String detail, List<Map<String, Object>> facts) {
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("schema_version", SCHEMA_VERSION);
        doc.put("generated_at", Instant.now().toString());
        doc.put("standard_family", STANDARD_FAMILY);
        doc.put("standard_release", STANDARD_RELEASE);
        doc.put("release_state_as_of", RELEASE_STATE_AS_OF);
        doc.put("library", LIBRARY);
        doc.put("library_version", LIBRARY_VERSION);
        doc.put("adapter_version", ADAPTER_VERSION);
        doc.put("message_identifier", mid);
        doc.put("input_sha256", sha);
        doc.put("parse_status", parseStatus);
        doc.put("detail", detail);
        doc.put("facts", facts);
        return doc;
    }

    /**
     * Walk DOM del modelo marshalleado. Un fact por elemento hoja
     * (texto) y por atributo. occurrence = indice entre hermanos del
     * mismo local-name bajo el mismo padre; evidence_locator =
     * path completamente indexado.
     */
    static List<Map<String, Object>> extractFacts(
            AbstractMX mx, String mid, String sha) {
        List<Map<String, Object>> facts = new ArrayList<>();
        Element doc = mx.element();
        if (doc != null) {
            walk(doc, "", facts, mid, sha);
        }
        AppHdr hdr = mx.getAppHdr();
        if (hdr != null && hdr.element() != null) {
            walk(hdr.element(), "", facts, mid, sha);
        }
        return facts;
    }

    private static void walk(Element el, String parentPath,
            List<Map<String, Object>> facts, String mid, String sha) {
        String name = el.getLocalName() != null
                ? el.getLocalName() : el.getTagName();
        int occ = siblingOccurrence(el);
        String path = parentPath + "/" + name;
        String locator = "element:" + indexedPath(el);

        NamedNodeMap attrs = el.getAttributes();
        List<String> attrNames = new ArrayList<>();
        for (int a = 0; a < attrs.getLength(); a++) {
            String an = attrs.item(a).getNodeName();
            if (an.startsWith("xmlns")) {
                continue;
            }
            attrNames.add(an);
        }
        java.util.Collections.sort(attrNames);
        for (String an : attrNames) {
            Attr attr = el.getAttributeNode(an);
            Map<String, Object> f = baseFact(mid, sha);
            f.put("model_path", path + "/@" + an);
            f.put("value", attr.getValue());
            f.put("occurrence", 0);
            f.put("evidence_locator", locator + "/@" + an);
            facts.add(f);
        }

        NodeList children = el.getChildNodes();
        boolean hasElementChild = false;
        for (int i = 0; i < children.getLength(); i++) {
            if (children.item(i).getNodeType() == Node.ELEMENT_NODE) {
                hasElementChild = true;
                break;
            }
        }
        if (!hasElementChild) {
            Map<String, Object> f = baseFact(mid, sha);
            f.put("model_path", path);
            f.put("value", el.getTextContent());
            f.put("occurrence", occ);
            f.put("evidence_locator", locator);
            facts.add(f);
            return;
        }
        for (int i = 0; i < children.getLength(); i++) {
            Node n = children.item(i);
            if (n.getNodeType() == Node.ELEMENT_NODE) {
                walk((Element) n, path, facts, mid, sha);
            }
        }
    }

    private static int siblingOccurrence(Element el) {
        String name = el.getLocalName() != null
                ? el.getLocalName() : el.getTagName();
        int occ = 0;
        Node sib = el.getPreviousSibling();
        while (sib != null) {
            if (sib.getNodeType() == Node.ELEMENT_NODE) {
                Element e = (Element) sib;
                String sn = e.getLocalName() != null
                        ? e.getLocalName() : e.getTagName();
                if (sn.equals(name)) {
                    occ++;
                }
            }
            sib = sib.getPreviousSibling();
        }
        return occ;
    }

    /** Path completo con [occ] en cada nivel: /A[0]/B[2]/C[0]. */
    private static String indexedPath(Element el) {
        List<String> steps = new ArrayList<>();
        Node cur = el;
        while (cur instanceof Element) {
            Element e = (Element) cur;
            String name = e.getLocalName() != null
                    ? e.getLocalName() : e.getTagName();
            steps.add(0, name + "[" + siblingOccurrence(e) + "]");
            cur = e.getParentNode();
        }
        return "/" + String.join("/", steps);
    }

    private static Map<String, Object> baseFact(String mid, String sha) {
        Map<String, Object> f = new LinkedHashMap<>();
        f.put("message_identifier", mid);
        f.put("input_sha256", sha);
        return f;
    }

    private static String sha256hex(byte[] data) {
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder sb = new StringBuilder(d.length * 2);
            for (byte b : d) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            return null;
        }
    }
}
