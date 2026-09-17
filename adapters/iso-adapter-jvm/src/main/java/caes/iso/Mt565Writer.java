package caes.iso;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.prowidesoftware.swift.model.SwiftBlock1;
import com.prowidesoftware.swift.model.SwiftBlock2Input;
import com.prowidesoftware.swift.model.SwiftBlock4;
import com.prowidesoftware.swift.model.SwiftMessage;
import com.prowidesoftware.swift.model.Tag;

/**
 * P5.5 — modo writer del adapter (ADR-010): la generacion SWIFT vive
 * fuera del core, aqui, sobre Prowide pinneado.
 *
 * Entrada por stdin: doc CA_ES_MT565_PROJECTION_V1 ya validado por el
 * core (solo acepta projection_status SERIALIZABLE; el mapping de
 * campos llega preregistrado en fields[] y el adapter solo ensambla).
 *
 * Salida por stdout: doc CA_ES_MT565_FIN_V1 (siempre JSON), con el FIN
 * completo en "fin" y su sha256.
 *
 * Exit codes: 0 OK / 2 INPUT_ERROR / 4 ADAPTER_ERROR.
 * Nunca se escribe contenido FIN ni de instruccion a stderr.
 */
public final class Mt565Writer {

    static final String SCHEMA_VERSION = "CA_ES_MT565_FIN_V1";
    static final String PROJECTION_SCHEMA = "CA_ES_MT565_PROJECTION_V1";

    static final int EXIT_OK = 0;
    static final int EXIT_INPUT_ERROR = 2;
    static final int EXIT_ADAPTER_ERROR = 4;

    private Mt565Writer() {
    }

    static IsoAdapter.Result mainResult() throws IOException {
        return run(System.in.readAllBytes());
    }

    static IsoAdapter.Result run(byte[] raw) {
        String sha = sha256hex(raw);
        Map<String, Object> proj;
        try {
            proj = new ObjectMapper().readValue(raw, Map.class);
        } catch (Exception e) {
            return inputError(sha,
                    "INVALID_JSON:" + e.getClass().getSimpleName());
        }
        if (proj == null
                || !PROJECTION_SCHEMA.equals(proj.get("schema"))) {
            return inputError(sha, "INVALID_PROJECTION_SCHEMA");
        }
        if (!"SERIALIZABLE".equals(proj.get("projection_status"))) {
            return inputError(sha, "PROJECTION_NOT_SERIALIZABLE");
        }
        Object envObj = proj.get("envelope");
        Object fieldsObj = proj.get("fields");
        if (!(envObj instanceof Map) || !(fieldsObj instanceof List)) {
            return inputError(sha, "INVALID_PROJECTION_STRUCTURE");
        }
        SwiftMessage sm;
        try {
            sm = build(castMap(envObj), castList(fieldsObj));
        } catch (IllegalArgumentException e) {
            return inputError(sha, e.getMessage());
        }
        try {
            String fin = sm.message();
            Map<String, Object> doc = envelope(sha, "OK", null);
            doc.put("fin", fin);
            doc.put("fin_sha256",
                    sha256hex(fin.getBytes(StandardCharsets.UTF_8)));
            return new IsoAdapter.Result(EXIT_OK, doc);
        } catch (Exception e) {
            return new IsoAdapter.Result(EXIT_ADAPTER_ERROR,
                    envelope(sha, "ADAPTER_ERROR",
                            e.getClass().getSimpleName()));
        }
    }

    private static SwiftMessage build(
            Map<String, Object> env, List<Object> fields) {
        String senderLt = req(env, "sender_lt");
        String receiverLt = req(env, "receiver_lt");
        String session = req(env, "session_number");
        String sequence = req(env, "sequence_number");
        String priority = req(env, "priority");

        SwiftBlock1 b1 = new SwiftBlock1();
        b1.setApplicationId("F");
        b1.setServiceId("01");
        b1.setLogicalTerminal(senderLt);
        b1.setSessionNumber(session);
        b1.setSequenceNumber(sequence);

        SwiftBlock2Input b2 = new SwiftBlock2Input();
        b2.setMessageType("565");
        b2.setReceiverAddress(receiverLt);
        b2.setMessagePriority(priority);

        List<Tag> tags = new ArrayList<>(fields.size());
        for (Object f : fields) {
            if (!(f instanceof Map)) {
                throw new IllegalArgumentException("INVALID_FIELD");
            }
            Map<?, ?> fm = (Map<?, ?>) f;
            Object tag = fm.get("tag");
            Object value = fm.get("value");
            if (!(tag instanceof String) || !(value instanceof String)) {
                throw new IllegalArgumentException("INVALID_FIELD");
            }
            tags.add(new Tag((String) tag, (String) value));
        }

        SwiftMessage sm = new SwiftMessage();
        sm.setBlock1(b1);
        sm.setBlock2(b2);
        sm.setBlock4(new SwiftBlock4(tags));
        return sm;
    }

    private static String req(Map<String, Object> env, String key) {
        Object v = env.get(key);
        if (!(v instanceof String) || ((String) v).isEmpty()) {
            throw new IllegalArgumentException("INVALID_ENVELOPE:" + key);
        }
        return (String) v;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> castMap(Object o) {
        return (Map<String, Object>) o;
    }

    private static List<Object> castList(Object o) {
        return (List<Object>) o;
    }

    private static IsoAdapter.Result inputError(String sha, String detail) {
        return new IsoAdapter.Result(EXIT_INPUT_ERROR,
                envelope(sha, "INPUT_ERROR", detail));
    }

    private static Map<String, Object> envelope(
            String sha, String writeStatus, String detail) {
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("schema_version", SCHEMA_VERSION);
        doc.put("generated_at", Instant.now().toString());
        doc.put("library", IsoAdapter.LIBRARY);
        doc.put("library_version", IsoAdapter.LIBRARY_VERSION);
        doc.put("adapter_version", IsoAdapter.ADAPTER_VERSION);
        doc.put("source_projection_sha256", sha);
        doc.put("write_status", writeStatus);
        doc.put("detail", detail);
        doc.put("fin", null);
        doc.put("fin_sha256", null);
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
