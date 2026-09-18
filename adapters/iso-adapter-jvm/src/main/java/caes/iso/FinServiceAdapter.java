package caes.iso;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

import com.prowidesoftware.swift.model.SwiftBlock1;
import com.prowidesoftware.swift.model.SwiftBlock4;
import com.prowidesoftware.swift.model.SwiftMessage;
import com.prowidesoftware.swift.model.Tag;

/**
 * P12.5 — modo `finsvc` del adapter: FIN service message (ACK/NAK,
 * service id 21) por stdin -> CA_ES_FIN_SERVICE_RECEIPT_V1 por stdout.
 *
 * El adapter EXTRAE campos; la correlación con sends almacenados la
 * decide el core Python (Prowide la deja explícitamente a la
 * aplicación — ver docs/p12/p125-fin-ack-nak.md).
 *
 * Contrato:
 * - stdout exclusivamente el JSON del contrato, incluso en error;
 * - diagnosticos a stderr, NUNCA contenido FIN;
 * - exit codes: 0 OK / 2 PARSE_ERROR / 3 NOT_SERVICE_MESSAGE_21 /
 *   4 ADAPTER_ERROR.
 */
public final class FinServiceAdapter {

    static final String SCHEMA_VERSION = "CA_ES_FIN_SERVICE_RECEIPT_V1";

    static final int EXIT_OK = 0;
    static final int EXIT_PARSE_ERROR = 2;
    static final int EXIT_NOT_SERVICE = 3;
    static final int EXIT_ADAPTER_ERROR = 4;

    private FinServiceAdapter() {
    }

    static IsoAdapter.Result mainResult() throws IOException {
        return run(System.in.readAllBytes());
    }

    static IsoAdapter.Result run(byte[] raw) {
        String sha = sha256hex(raw);
        if (raw.length == 0) {
            return result(EXIT_PARSE_ERROR,
                    envelope(sha, "PARSE_ERROR", "EMPTY_INPUT"));
        }
        String fin = new String(raw, StandardCharsets.UTF_8);
        SwiftMessage sm;
        try {
            sm = SwiftMessage.parse(fin);
        } catch (Exception e) {
            return result(EXIT_PARSE_ERROR,
                    envelope(sha, "PARSE_ERROR",
                            e.getClass().getSimpleName()));
        }
        if (sm == null || !sm.isServiceMessage21()) {
            return result(EXIT_NOT_SERVICE,
                    envelope(sha, "NOT_SERVICE_MESSAGE_21", null));
        }

        Map<String, Object> doc = envelope(sha, "OK", null);
        doc.put("service_id", "21");
        doc.put("is_ack", sm.isAck());
        doc.put("is_nack", sm.isNack());
        doc.put("field_177", tag(sm, "177"));
        doc.put("field_451", tag(sm, "451"));
        doc.put("field_405", tag(sm, "405"));
        doc.put("field_108", tag(sm, "108"));
        String mur;
        try {
            mur = sm.getMUR();
        } catch (Exception e) {
            mur = null;
        }
        doc.put("mur", mur);
        doc.put("embedded_copy", embeddedCopy(sm));
        return result(EXIT_OK, doc);
    }

    /**
     * Referencia al mensaje original dentro del ACK/NAK. La forma mas
     * comun (SAA AFT) es la copia completa como unparsed text; de ella
     * se extrae el MIR (LT+session+sequence de block1), el tipo MT y
     * el SEME de block4 para correlación determinista en el core.
     */
    private static Map<String, Object> embeddedCopy(SwiftMessage sm) {
        Map<String, Object> copy = new LinkedHashMap<>();
        String fin;
        try {
            if (sm.getUnparsedTexts() == null
                    || sm.getUnparsedTexts().size() == 0) {
                copy.put("present", false);
                return copy;
            }
            fin = sm.getUnparsedTexts().getAsFINString();
        } catch (Exception e) {
            copy.put("present", false);
            return copy;
        }
        if (fin == null || !fin.contains("{1:")) {
            copy.put("present", false);
            return copy;
        }
        SwiftMessage orig;
        try {
            orig = SwiftMessage.parse(fin);
        } catch (Exception e) {
            copy.put("present", false);
            return copy;
        }
        if (orig == null || orig.getBlock1() == null) {
            copy.put("present", false);
            return copy;
        }
        SwiftBlock1 b1 = orig.getBlock1();
        copy.put("present", true);
        copy.put("sha256",
                sha256hex(fin.getBytes(StandardCharsets.UTF_8)));
        copy.put("mir_lt", b1.getLogicalTerminal());
        copy.put("mir_session", b1.getSessionNumber());
        copy.put("mir_sequence", b1.getSequenceNumber());
        String mt = null;
        try {
            mt = orig.getMtId() != null
                    ? orig.getMtId().getMessageType() : null;
        } catch (Exception e) {
            mt = null;
        }
        copy.put("message_type", mt);
        copy.put("seme", semeOf(orig));
        return copy;
    }

    /** 20C::SEME//&lt;ref&gt; de block4 — la referencia de negocio. */
    private static String semeOf(SwiftMessage sm) {
        SwiftBlock4 b4 = sm.getBlock4();
        if (b4 == null) {
            return null;
        }
        for (Tag t : b4.getTags()) {
            if ("20C".equals(t.getName()) && t.getValue() != null
                    && t.getValue().startsWith(":SEME//")) {
                return t.getValue().substring(":SEME//".length());
            }
        }
        return null;
    }

    private static String tag(SwiftMessage sm, String name) {
        SwiftBlock4 b4 = sm.getBlock4();
        if (b4 == null) {
            return null;
        }
        Tag t = b4.getTagByName(name);
        return t != null ? t.getValue() : null;
    }

    private static IsoAdapter.Result result(int code,
            Map<String, Object> doc) {
        return new IsoAdapter.Result(code, doc);
    }

    private static Map<String, Object> envelope(
            String sha, String parseStatus, String detail) {
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("schema", SCHEMA_VERSION);
        doc.put("generated_at", Instant.now().toString());
        doc.put("library", IsoAdapter.LIBRARY);
        doc.put("library_version", IsoAdapter.LIBRARY_VERSION);
        doc.put("adapter_version", IsoAdapter.ADAPTER_VERSION);
        doc.put("input_sha256", sha);
        doc.put("parse_status", parseStatus);
        doc.put("detail", detail);
        doc.put("service_id", null);
        doc.put("is_ack", false);
        doc.put("is_nack", false);
        doc.put("field_177", null);
        doc.put("field_451", null);
        doc.put("field_405", null);
        doc.put("field_108", null);
        doc.put("mur", null);
        doc.put("embedded_copy", null);
        return doc;
    }

    private static String sha256hex(byte[] data) {
        try {
            byte[] d = java.security.MessageDigest
                    .getInstance("SHA-256").digest(data);
            StringBuilder sb = new StringBuilder(d.length * 2);
            for (byte b : d) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            return null;
        }
    }
}
