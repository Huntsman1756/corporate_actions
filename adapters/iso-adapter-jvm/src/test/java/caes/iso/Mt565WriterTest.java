package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.prowidesoftware.swift.model.mt.mt5xx.MT565;
import org.junit.jupiter.api.Test;

/** P5.5 — writer MT565: ensambla el projection preregistrado. */
class Mt565WriterTest {

    private static byte[] projectionJson() throws Exception {
        Map<String, Object> env = new LinkedHashMap<>();
        env.put("sender_lt", "BANKESMMAXXXX");
        env.put("receiver_lt", "BANKDEFFXXXX");
        env.put("session_number", "0000");
        env.put("sequence_number", "000005");
        env.put("priority", "N");

        List<Map<String, String>> fields = List.of(
                Map.of("tag", "16R", "value", "GENL"),
                Map.of("tag", "20C", "value", ":SEME//INS-0001"),
                Map.of("tag", "20C", "value", ":CORP//CORP-REF-42"),
                Map.of("tag", "23G", "value", "NEWM"),
                Map.of("tag", "22F", "value", ":CAEV//VOLU"),
                Map.of("tag", "16R", "value", "LINK"),
                Map.of("tag", "13A", "value", ":LINK//564"),
                Map.of("tag", "20C", "value", ":RELA//REFSEME004"),
                Map.of("tag", "16S", "value", "LINK"),
                Map.of("tag", "16S", "value", "GENL"),
                Map.of("tag", "16R", "value", "USECU"),
                Map.of("tag", "35B", "value", "ISIN ES0105448007"),
                Map.of("tag", "16R", "value", "ACCTINFO"),
                Map.of("tag", "97A", "value", ":SAFE//ACC-01"),
                Map.of("tag", "16S", "value", "ACCTINFO"),
                Map.of("tag", "16S", "value", "USECU"),
                Map.of("tag", "16R", "value", "CAINST"),
                Map.of("tag", "13A", "value", ":CAON//001"),
                Map.of("tag", "22F", "value", ":CAOP//CASH"),
                Map.of("tag", "36B", "value", ":QINS//UNIT/12500,"),
                Map.of("tag", "16S", "value", "CAINST"));

        Map<String, Object> proj = new LinkedHashMap<>();
        proj.put("schema", "CA_ES_MT565_PROJECTION_V1");
        proj.put("projection_status", "SERIALIZABLE");
        proj.put("envelope", env);
        proj.put("fields", fields);
        return new ObjectMapper().writeValueAsBytes(proj);
    }

    @Test
    void serializableProjectionProducesParseableMt565() throws Exception {
        IsoAdapter.Result r = Mt565Writer.run(projectionJson());
        assertEquals(Mt565Writer.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("CA_ES_MT565_FIN_V1", doc.get("schema_version"));
        assertEquals("OK", doc.get("write_status"));
        assertEquals("SRU2025-10.3.19", doc.get("library_version"));
        String fin = (String) doc.get("fin");
        assertNotNull(fin);
        assertEquals(64, ((String) doc.get("fin_sha256")).length());
        assertNotNull(doc.get("source_projection_sha256"));

        // round-trip sobre el modelo Prowide, no string-contains
        MT565 mt = MT565.parse(fin);
        assertEquals("INS-0001",
                mt.getField20C().get(0).getReference());
        assertEquals("SEME",
                mt.getField20C().get(0).getQualifier());
        assertEquals("VOLU",
                mt.getField22F().get(0).getIndicator());
        String block4 = fin.substring(fin.indexOf("{4:"));
        assertTrue(block4.contains(":20C::CORP//CORP-REF-42"));
        assertTrue(block4.contains(":20C::RELA//REFSEME004"));
        assertTrue(block4.contains(":13A::LINK//564"));
        assertTrue(block4.contains("ISIN ES0105448007"));
        assertTrue(block4.contains(":97A::SAFE//ACC-01"));
        assertTrue(block4.contains(":13A::CAON//001"));
        assertTrue(block4.contains(":22F::CAOP//CASH"));
        assertTrue(block4.contains(":36B::QINS//UNIT/12500,"));
        assertTrue(block4.contains(":16R:CAINST"));
        assertTrue(block4.contains(":16S:CAINST"));
    }

    @Test
    void sameProjectionIsByteDeterministic() throws Exception {
        String a = (String) Mt565Writer.run(projectionJson()).doc()
                .get("fin");
        String b = (String) Mt565Writer.run(projectionJson()).doc()
                .get("fin");
        assertEquals(a, b);
    }

    @Test
    void nonSerializableRejected() throws Exception {
        Map<String, Object> proj = new LinkedHashMap<>();
        proj.put("schema", "CA_ES_MT565_PROJECTION_V1");
        proj.put("projection_status", "NOT_SERIALIZABLE");
        proj.put("envelope", Map.of());
        proj.put("fields", List.of());
        IsoAdapter.Result r = Mt565Writer.run(
                new ObjectMapper().writeValueAsBytes(proj));
        assertEquals(Mt565Writer.EXIT_INPUT_ERROR, r.exitCode());
        assertEquals("INPUT_ERROR", r.doc().get("write_status"));
        assertNull(r.doc().get("fin"));
    }

    @Test
    void invalidJsonAndWrongSchemaRejected() throws Exception {
        IsoAdapter.Result r = Mt565Writer.run(
                "not json".getBytes(StandardCharsets.UTF_8));
        assertEquals(Mt565Writer.EXIT_INPUT_ERROR, r.exitCode());

        Map<String, Object> proj = new LinkedHashMap<>();
        proj.put("schema", "CA_ES_OTHER_V1");
        proj.put("projection_status", "SERIALIZABLE");
        r = Mt565Writer.run(new ObjectMapper().writeValueAsBytes(proj));
        assertEquals(Mt565Writer.EXIT_INPUT_ERROR, r.exitCode());
    }

    @Test
    void missingEnvelopeFieldRejected() throws Exception {
        Map<String, Object> proj = new LinkedHashMap<>();
        proj.put("schema", "CA_ES_MT565_PROJECTION_V1");
        proj.put("projection_status", "SERIALIZABLE");
        proj.put("envelope", Map.of("sender_lt", "BANKESMMAXXXX"));
        proj.put("fields", List.of(
                Map.of("tag", "16R", "value", "GENL")));
        IsoAdapter.Result r = Mt565Writer.run(
                new ObjectMapper().writeValueAsBytes(proj));
        assertEquals(Mt565Writer.EXIT_INPUT_ERROR, r.exitCode());
        String detail = String.valueOf(r.doc().get("detail"));
        assertFalse(detail.contains("BANKESMMAXXXX"),
                "detail no filtra valores del envelope");
    }
}
