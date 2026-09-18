package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

/**
 * P13 — custody feed formats through the generic facts extractors.
 * Solo se verifica que el boundary JVM parsea y emite facts con la
 * evidencia que la proyeccion Python necesita; la semantica de
 * negocio vive en el core.
 */
class CustodyFactsTest {

    private static byte[] fixture(String name) throws IOException {
        try (InputStream in = CustodyFactsTest.class
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

    private static boolean hasFact(List<Map<String, Object>> facts,
            String tag, String qualifier) {
        return facts.stream().anyMatch(f ->
                tag.equals(f.get("source_tag"))
                        && (qualifier == null
                            || qualifier.equals(
                                f.get("source_qualifier"))));
    }

    private static boolean hasPath(List<Map<String, Object>> facts,
            String needle) {
        return facts.stream().anyMatch(f ->
                String.valueOf(f.get("model_path")).contains(needle));
    }

    @Test
    void mt535EmitsPaginationAccountAndBalanceFacts() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt535-complete.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("MT535", doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        assertTrue(hasFact(facts, "28E", null));
        assertTrue(hasFact(facts, "20C", "SEME"));
        assertTrue(hasFact(facts, "97A", "SAFE"));
        assertTrue(hasFact(facts, "98A", "STAT"));
        assertTrue(hasFact(facts, "35B", null));
        assertTrue(hasFact(facts, "93B", "AGGR"));
        assertTrue(hasFact(facts, "93B", "AVAI"));
        // sequence paths preserve FIN/SUBBAL context for grouping
        assertTrue(facts.stream().anyMatch(f ->
                String.valueOf(f.get("sequence")).contains("SUBBAL")));
    }

    @Test
    void mt940EmitsStatementAndEntryFacts() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt940.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("MT940", doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        assertTrue(hasFact(facts, "20", null));
        assertTrue(hasFact(facts, "25", null));
        assertTrue(hasFact(facts, "28C", null));
        assertTrue(hasFact(facts, "61", null));
        assertTrue(hasFact(facts, "86", null));
        // two :61: lines -> both occurrences present
        long entryOccurrences = facts.stream().filter(f ->
                "61".equals(f.get("source_tag"))
                        && String.valueOf(f.get("field_path"))
                                .endsWith(".amount"))
                .count();
        assertTrue(entryOccurrences >= 2,
                "expected >=2 field61 amount facts");
    }

    @Test
    void semt002EmitsStatementAndBalanceFacts() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("semt002-00112.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("semt.002.001.12",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        assertTrue(hasPath(facts, "/SfkpgAcct/Id"));
        assertTrue(hasPath(facts, "/StmtGnlDtls/StmtDtTm/Dt"));
        assertTrue(hasPath(facts, "/Pgntn/LastPgInd"));
        assertTrue(hasPath(facts, "/UpdTp/Cd"));
        assertTrue(hasPath(facts, "/BalForAcct/FinInstrmId/ISIN"));
        assertTrue(hasPath(facts, "/BalForAcct/AggtBal/Qty/Qty/Qty/Unit"));
        // two BalForAcct -> disambiguated via indexed evidence_locator
        assertTrue(facts.stream().anyMatch(f ->
                String.valueOf(f.get("evidence_locator"))
                        .contains("/BalForAcct[1]/FinInstrmId")));
    }

    @Test
    void camt054EmitsEntryAndReferenceFacts() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("camt054-00113.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("camt.054.001.13",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        assertTrue(hasPath(facts, "/Acct/Id/IBAN"));
        assertTrue(hasPath(facts, "/Ntry/NtryRef"));
        assertTrue(hasPath(facts, "/Ntry/CdtDbtInd"));
        assertTrue(hasPath(facts, "/Ntry/Amt"));
        assertTrue(hasPath(facts, "/Ntry/Sts/Cd"));
        assertTrue(hasPath(facts, "/Ntry/BookgDt/Dt"));
        assertTrue(hasPath(facts, "/Ntry/ValDt/Dt"));
        assertTrue(hasPath(facts, "/TxDtls/Refs/EndToEndId"));
        // Amt carries the Ccy attribute as an attribute fact
        assertTrue(facts.stream().anyMatch(f ->
                String.valueOf(f.get("model_path"))
                        .endsWith("/Ntry/Amt/@Ccy")
                        && "EUR".equals(f.get("value"))));
    }

    @Test
    void mt950EmitsStatementAndEntryFacts() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt950.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("MT950", doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        assertTrue(hasFact(facts, "20", null));
        assertTrue(hasFact(facts, "25", null));
        assertTrue(hasFact(facts, "28C", null));
        assertTrue(hasFact(facts, "61", null));
        assertTrue(hasFact(facts, "62F", null));
    }

    @Test
    void camt053EmitsStatementEntryAndBalanceFacts() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("camt053-00113.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("camt.053.001.13",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        assertTrue(hasPath(facts, "/Stmt/Id"));
        assertTrue(hasPath(facts, "/Acct/Id/IBAN"));
        assertTrue(hasPath(facts, "/Ntry/NtryRef"));
        assertTrue(hasPath(facts, "/Ntry/CdtDbtInd"));
        assertTrue(hasPath(facts, "/Bal/Tp/CdOrPrtry/Cd"));
        assertTrue(hasPath(facts, "/TxDtls/Refs/EndToEndId"));
    }
}
