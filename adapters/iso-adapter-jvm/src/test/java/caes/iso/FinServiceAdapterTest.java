package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.util.Map;

import org.junit.jupiter.api.Test;

/**
 * P12.5 — FinServiceAdapter (modo finsvc): parseo real Prowide de
 * service messages FIN 21 (ACK/NAK) y extraccion de la copia
 * embebida para correlacion MIR+SEME.
 */
class FinServiceAdapterTest {

    private static final String ORIG_FIN =
            "{1:F01LITEBEBBAXXX0066000079}{2:I565BANKGB2LXXXXN}{4:\n"
            + ":16R:GENL\n"
            + ":20C::SEME//INS-0001\n"
            + ":20C::CORP//CORP-REF-42\n"
            + ":23G:NEWM\n"
            + ":16S:GENL\n"
            + "-}";

    private static final String ACK =
            "{1:F21LITEBEBBAXXX0066000080}{4:{177:2607160901}{451:0}}"
            + ORIG_FIN
            + "{5:{CHK:7602B010CF31}{TNG:}}";

    private static final String NAK =
            "{1:F21LITEBEBBAXXX0066000081}{4:{177:2607160902}{451:1}"
            + "{405:T33002}}"
            + ORIG_FIN
            + "{5:{CHK:7602B010CF32}{TNG:}}";

    @SuppressWarnings("unchecked")
    private static Map<String, Object> embedded(Map<String, Object> doc) {
        return (Map<String, Object>) doc.get("embedded_copy");
    }

    @Test
    void ackParsesServiceFieldsAndEmbeddedCopy() {
        IsoAdapter.Result r =
                FinServiceAdapter.run(ACK.getBytes());
        assertEquals(FinServiceAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("CA_ES_FIN_SERVICE_RECEIPT_V1",
                doc.get("schema"));
        assertEquals("OK", doc.get("parse_status"));
        assertEquals("21", doc.get("service_id"));
        assertEquals(true, doc.get("is_ack"));
        assertEquals(false, doc.get("is_nack"));
        assertEquals("0", doc.get("field_451"));
        assertNull(doc.get("field_405"));

        Map<String, Object> copy = embedded(doc);
        assertEquals(true, copy.get("present"));
        assertEquals("LITEBEBBAXXX", copy.get("mir_lt"));
        assertEquals("0066", copy.get("mir_session"));
        assertEquals("000079", copy.get("mir_sequence"));
        assertEquals("565", copy.get("message_type"));
        assertEquals("INS-0001", copy.get("seme"));
        assertNotNull(copy.get("sha256"));
    }

    @Test
    void nakParsesErrorCode() {
        IsoAdapter.Result r =
                FinServiceAdapter.run(NAK.getBytes());
        assertEquals(FinServiceAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals(true, doc.get("is_nack"));
        assertEquals("1", doc.get("field_451"));
        assertEquals("T33002", doc.get("field_405"));
    }

    @Test
    void ackWithoutEmbeddedCopyReportsAbsent() {
        String bare =
                "{1:F21LITEBEBBAXXX0066000080}"
                + "{4:{177:2607160901}{451:0}{108:MURREF001}}";
        IsoAdapter.Result r =
                FinServiceAdapter.run(bare.getBytes());
        assertEquals(FinServiceAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals(false, embedded(doc).get("present"));
    }

    @Test
    void regularUserMessageRejected() {
        IsoAdapter.Result r =
                FinServiceAdapter.run(ORIG_FIN.getBytes());
        assertEquals(FinServiceAdapter.EXIT_NOT_SERVICE, r.exitCode());
        assertEquals("NOT_SERVICE_MESSAGE_21",
                r.doc().get("parse_status"));
    }

    @Test
    void emptyInputIsParseError() {
        IsoAdapter.Result r =
                FinServiceAdapter.run(new byte[0]);
        assertEquals(FinServiceAdapter.EXIT_PARSE_ERROR, r.exitCode());
    }

    @Test
    void garbageIsNotServiceMessage() {
        // Prowide parsea de forma tolerante: texto arbitrario produce
        // un mensaje no-21, clasificado NOT_SERVICE (fail closed en
        // el core igual que PARSE_ERROR — ambos quedan quarantined).
        IsoAdapter.Result r = FinServiceAdapter.run(
                "this is not a fin message".getBytes());
        assertEquals(FinServiceAdapter.EXIT_NOT_SERVICE, r.exitCode());
        assertEquals("NOT_SERVICE_MESSAGE_21",
                r.doc().get("parse_status"));
    }
}
