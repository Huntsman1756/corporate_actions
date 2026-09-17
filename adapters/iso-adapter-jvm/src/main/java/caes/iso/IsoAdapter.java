package caes.iso;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.prowidesoftware.swift.model.SwiftBlock4;
import com.prowidesoftware.swift.model.SwiftMessage;
import com.prowidesoftware.swift.model.Tag;
import com.prowidesoftware.swift.model.field.Field;

/**
 * P4.0 — ISO adapter boundary (ADR-010).
 *
 * FIN raw (MT564/MT566) por stdin -> CA_ES_SWIFT_MT_FACTS_V1 por stdout.
 *
 * Contrato:
 * - stdout exclusivamente el JSON del contrato, incluso en error;
 * - diagnosticos a stderr, NUNCA contenido FIN (ni aqui ni en logs);
 * - parse_status textual separado del exit code numerico;
 * - read-only: no genera SWIFT ni proyecta al canon.
 *
 * Exit codes: 0 OK, 2 PARSE_ERROR, 3 UNSUPPORTED_MESSAGE_TYPE,
 * 4 ADAPTER_ERROR.
 */
public final class IsoAdapter {

    static final String SCHEMA_VERSION = "CA_ES_SWIFT_MT_FACTS_V1";
    static final String ADAPTER_VERSION = "0.1.0";
    static final String LIBRARY = "prowide-core";
    static final String LIBRARY_VERSION = "SRU2025-10.3.19";
    static final String STANDARD_FAMILY = "ISO15022";
    static final String STANDARD_RELEASE = "SRU2025";
    static final String RELEASE_STATE_AS_OF = "2026-09-16";

    static final int EXIT_OK = 0;
    static final int EXIT_PARSE_ERROR = 2;
    static final int EXIT_UNSUPPORTED = 3;
    static final int EXIT_ADAPTER_ERROR = 4;

    private static final Set<String> SUPPORTED =
            Set.of("564", "566", "567");
    private static final String FIELD_PKG =
            "com.prowidesoftware.swift.model.field.Field";

    public static final class Result {
        private final int exitCode;
        private final Map<String, Object> doc;

        Result(int exitCode, Map<String, Object> doc) {
            this.exitCode = exitCode;
            this.doc = doc;
        }

        public int exitCode() {
            return exitCode;
        }

        public Map<String, Object> doc() {
            return doc;
        }
    }

    public static void main(String[] args) {
        if (args.length > 0 && "mt565".equals(args[0])) {
            Result w;
            try {
                w = Mt565Writer.mainResult();
            } catch (Throwable t) {
                w = new Result(Mt565Writer.EXIT_ADAPTER_ERROR,
                        new LinkedHashMap<>());
                w.doc().put("schema_version", Mt565Writer.SCHEMA_VERSION);
                w.doc().put("write_status", "ADAPTER_ERROR");
                w.doc().put("detail", t.getClass().getSimpleName());
            }
            emit(w);
            return;
        }
        Result r;
        try {
            r = run(System.in.readAllBytes());
        } catch (Throwable t) {
            // ultimo recurso: JSON de error, sin FIN
            r = new Result(EXIT_ADAPTER_ERROR,
                    envelope(null, null, "ADAPTER_ERROR",
                             t.getClass().getSimpleName(), List.of()));
        }
        emit(r);
    }

    static void emit(Result r) {
        try {
            String json = new ObjectMapper()
                    .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
                    .writerWithDefaultPrettyPrinter()
                    .writeValueAsString(r.doc());
            System.out.print(json);
            System.out.print("\n");
        } catch (IOException e) {
            System.err.println("SERIALIZATION_FAILURE "
                    + e.getClass().getSimpleName());
            System.exit(EXIT_ADAPTER_ERROR);
        }
        if (r.doc().get("detail") != null) {
            System.err.println("detail=" + r.doc().get("detail"));
        }
        System.exit(r.exitCode());
    }

    /** Parsea FIN raw y produce el doc del contrato. Pura/testeable. */
    public static Result run(byte[] raw) {
        String sha = sha256hex(raw);
        if (raw.length == 0) {
            return new Result(EXIT_PARSE_ERROR,
                    envelope(sha, null, "PARSE_ERROR",
                             "EMPTY_INPUT", List.of()));
        }
        String fin = new String(raw, StandardCharsets.UTF_8);
        SwiftMessage sm;
        try {
            sm = SwiftMessage.parse(fin);
        } catch (Exception e) {
            return new Result(EXIT_PARSE_ERROR,
                    envelope(sha, null, "PARSE_ERROR",
                             e.getClass().getSimpleName(), List.of()));
        }
        String mt;
        try {
            mt = sm.getMtId() != null ? sm.getMtId().getMessageType() : null;
        } catch (Exception e) {
            mt = null;
        }
        if (mt == null) {
            // ni siquiera identificable como tipo MT -> no parseable
            // a efectos del contrato (Prowide es tolerante; mtId null
            // equivale a "no es un FIN reconocible")
            return new Result(EXIT_PARSE_ERROR,
                    envelope(sha, null, "PARSE_ERROR",
                             "UNRECOGNIZED_MESSAGE", List.of()));
        }
        if (!SUPPORTED.contains(mt)) {
            return new Result(EXIT_UNSUPPORTED,
                    envelope(sha, "MT" + mt, "UNSUPPORTED_MESSAGE_TYPE",
                             "MT" + mt, List.of()));
        }
        List<Map<String, Object>> facts;
        try {
            facts = extractFacts(sm, "MT" + mt, sha);
        } catch (Exception e) {
            return new Result(EXIT_ADAPTER_ERROR,
                    envelope(sha, "MT" + mt, "ADAPTER_ERROR",
                             e.getClass().getSimpleName(), List.of()));
        }
        return new Result(EXIT_OK,
                envelope(sha, "MT" + mt, "OK", null, facts));
    }

    private static Map<String, Object> envelope(
            String sha, String mtId, String parseStatus,
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
        doc.put("message_identifier", mtId);
        doc.put("input_sha256", sha);
        doc.put("parse_status", parseStatus);
        doc.put("detail", detail);
        doc.put("facts", facts);
        return doc;
    }

    /**
     * Recorre block4 siguiendo la pila 16R/16S y emite un fact por
     * componente de cada campo. El qualifier se extrae via la clase
     * FieldNN de Prowide (reflexion); si no existe, fact crudo.
     */
    static List<Map<String, Object>> extractFacts(
            SwiftMessage sm, String mtId, String sha) {
        List<Map<String, Object>> facts = new ArrayList<>();
        SwiftBlock4 b4 = sm.getBlock4();
        if (b4 == null) {
            return facts;
        }
        Deque<String> stack = new ArrayDeque<>();
        Map<String, Integer> occurrences = new HashMap<>();
        List<Tag> tags = b4.getTags();
        for (int i = 0; i < tags.size(); i++) {
            Tag tag = tags.get(i);
            String name = tag.getName();
            String value = tag.getValue();
            if ("16R".equals(name)) {
                stack.push(value != null ? value : "?");
                continue;
            }
            if ("16S".equals(name)) {
                if (!stack.isEmpty()) {
                    stack.pop();
                }
                continue;
            }
            List<String> seqList = new ArrayList<>(stack);
            java.util.Collections.reverse(seqList);
            String seqPath = String.join("/", seqList);

            Field field = tryField(name, value);
            String qualifier = qualifierOf(field, value);

            String occKey = seqPath + "|" + name + "|"
                    + (qualifier != null ? qualifier : "");
            int occ = occurrences.merge(occKey, 1, Integer::sum) - 1;

            if (field != null) {
                List<String> comps = field.getComponents();
                for (int c = 0; c < comps.size(); c++) {
                    String compVal = comps.get(c);
                    if (compVal == null || compVal.isEmpty()) {
                        continue;
                    }
                    String label;
                    try {
                        label = field.getComponentLabel(c + 1);
                    } catch (Exception e) {
                        label = "component" + (c + 1);
                    }
                    if ("Qualifier".equals(label)
                            || "Conditional Qualifier".equals(label)) {
                        // ya viaja como source_qualifier del fact
                        continue;
                    }
                    facts.add(fact(mtId, seqPath, name, qualifier,
                            label, compVal, occ, i, c, sha));
                }
            } else {
                facts.add(fact(mtId, seqPath, name, qualifier,
                        "value", value, occ, i, -1, sha));
            }
        }
        return facts;
    }

    private static Field tryField(String tagName, String value) {
        try {
            Class<?> cls = Class.forName(FIELD_PKG + tagName);
            Constructor<?> ctor = cls.getConstructor(String.class);
            return (Field) ctor.newInstance(value);
        } catch (Exception e) {
            return null;
        }
    }

    /** getQualifier() vive en las subclases, no en Field base. */
    private static String qualifierOf(Field field, String rawValue) {
        if (field != null) {
            try {
                Object q = field.getClass()
                        .getMethod("getQualifier").invoke(field);
                if (q != null && !String.valueOf(q).isEmpty()) {
                    return String.valueOf(q);
                }
            } catch (Exception e) {
                // sin qualifier -> fallback lexico
            }
        }
        if (rawValue != null && rawValue.length() > 7
                && rawValue.charAt(0) == ':'
                && rawValue.charAt(6) == '/'
                && rawValue.charAt(7) == '/') {
            return rawValue.substring(1, 6);
        }
        return null;
    }

    private static Map<String, Object> fact(
            String mtId, String seqPath, String tag, String qualifier,
            String label, String value, int occurrence,
            int tagIndex, int compIndex, String sha) {
        StringBuilder path = new StringBuilder(mtId);
        if (!seqPath.isEmpty()) {
            path.append('.').append(seqPath.replace('/', '.'));
        }
        path.append('.').append(tag);
        if (qualifier != null) {
            path.append(':').append(qualifier);
        }
        if (occurrence > 0) {
            path.append('[').append(occurrence).append(']');
        }
        path.append('.').append(label.toLowerCase());

        Map<String, Object> f = new LinkedHashMap<>();
        f.put("message_identifier", mtId);
        f.put("field_path", path.toString());
        f.put("value", value);
        f.put("source_tag", tag);
        f.put("source_qualifier", qualifier);
        f.put("sequence", seqPath);
        f.put("occurrence", occurrence);
        f.put("evidence_locator",
                "block4.tag[" + tagIndex + "]"
                        + (compIndex >= 0
                           ? ".component[" + compIndex + "]" : ""));
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
