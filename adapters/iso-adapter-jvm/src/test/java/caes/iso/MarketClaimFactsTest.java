package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

/**
 * P16 — Market Claims seev.050-053 a traves del extractor generico
 * de facts MX. Solo se verifica que el boundary JVM emite los facts
 * que la proyeccion Python consume; la semantica vive en el core.
 * Versiones soportadas = las presentes en el pin SRU2025.
 */
class MarketClaimFactsTest {

    private static byte[] fixture(String name) throws IOException {
        try (InputStream in = MarketClaimFactsTest.class
                .getResourceAsStream("/" + name)) {
            assertNotNull(in, "fixture " + name);
            return in.readAllBytes();
        }
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> facts(
            Map<String, Object> doc) {
        return (List<Map<String, Object>>) doc.get("facts");
    }

    private static boolean hasPath(List<Map<String, Object>> facts,
            String needle) {
        return facts.stream().anyMatch(f ->
                String.valueOf(f.get("model_path")).contains(needle));
    }

    @Test
    void seev050EmitsClaimOperands() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("seev050-mktclm.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("seev.050.001.03",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasPath(facts, "/TxRef/AcctSvcrTxId"));
        assertTrue(hasPath(facts, "/CorpActnEvtId"));
        assertTrue(hasPath(facts, "/RltdSttlmInstrDtls/RltdSttlmInstrId"));
        assertTrue(hasPath(facts, "/TrfOfPrcdsTpInd"));
        assertTrue(hasPath(facts, "/MktClmTp"));
        assertTrue(hasPath(facts, "/MktClmDtls/CshMvmntDtls"));
        assertTrue(hasPath(facts, "/EntitldAmt"));
    }

    @Test
    void seev052EmitsStatusChoice() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("seev052-accepted.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("seev.052.001.03",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasPath(facts, "/MktClmCreId/Id"));
        assertTrue(hasPath(facts, "/MktClmPrcgSts/AccptdForFrthrPrcg"));
    }

    @Test
    void seev051EmitsCancellationRequest() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("seev051-cxl.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("seev.051.001.02",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasPath(facts, "/MktClmCreId/Id"));
        assertTrue(hasPath(facts, "/TxRef/AcctSvcrTxId"));
    }

    @Test
    void seev053EmitsCancellationStatus() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("seev053-cxl-accepted.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("seev.053.001.03",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasPath(facts, "/MktClmCxlReqId/Id"));
        assertTrue(hasPath(facts, "/MktClmCxlReqSts/Accptd"));
    }
}
