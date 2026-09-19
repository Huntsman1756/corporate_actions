package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

/**
 * P17 — MT540-548 / sese.023-025 a traves de los extractores
 * genericos de facts. Solo se verifica que el boundary JVM emite
 * los facts que la normalizacion Python consume; la semantica
 * vive en el core. Versiones soportadas = pin SRU2025.
 */
class SettlementFactsTest {

    private static byte[] fixture(String name) throws IOException {
        try (InputStream in = SettlementFactsTest.class
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

    private static boolean hasFact(List<Map<String, Object>> facts,
            String tag, String qual) {
        return facts.stream().anyMatch(f ->
                tag.equals(f.get("source_tag"))
                        && qual.equals(f.get("source_qualifier")));
    }

    @Test
    void mt541EmitsInstructionOperands() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(
                fixture("mt541-rece.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("MT541", doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasFact(facts, "20C", "SEME"));
        assertTrue(hasFact(facts, "22H", "REDE"));
        assertTrue(hasFact(facts, "22H", "PAYM"));
        assertTrue(hasFact(facts, "98A", "SETT"));
        assertTrue(hasFact(facts, "36B", "SETT"));
        assertTrue(hasFact(facts, "97A", "SAFE"));
        assertTrue(facts.stream().anyMatch(f ->
                "35B".equals(f.get("source_tag"))));
    }

    @Test
    void mt545EmitsConfirmationOperands() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(
                fixture("mt545-conf.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        List<Map<String, Object>> facts = facts(r.doc());
        assertTrue(hasFact(facts, "20C", "SEME"));
        assertTrue(hasFact(facts, "20C", "RELA"));
        assertTrue(hasFact(facts, "36B", "ESTT"));
        assertTrue(hasFact(facts, "19A", "ESTT"));
    }

    @Test
    void mt548EmitsStatusOperands() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(
                fixture("mt548-status.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        List<Map<String, Object>> facts = facts(r.doc());
        assertTrue(hasFact(facts, "25D", "MTCH"));
        assertTrue(hasFact(facts, "25D", "SETT"));
    }

    @Test
    void sese023EmitsInstructionOperands() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("sese023-instr.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("sese.023.001.11",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasPath(facts, "/SctiesSttlmTxInstr/TxId"));
        assertTrue(hasPath(facts, "/SctiesMvmntTp"));
        assertTrue(hasPath(facts, "/SttlmTpAndAddtlParams/Pmt"));
        assertTrue(hasPath(facts, "/QtyAndAcctDtls/SttlmQty"));
        assertTrue(hasPath(facts, "/SfkpgAcct/Id"));
        assertTrue(hasPath(facts, "/FinInstrmId/ISIN"));
        assertTrue(hasPath(facts, "/TradDtls/SttlmDt"));
    }

    @Test
    void sese024EmitsStatusOperands() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("sese024-pdg.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        List<Map<String, Object>> facts = facts(r.doc());
        assertTrue(hasPath(facts, "/TxId/AcctSvcrTxId"));
        assertTrue(hasPath(facts, "/SttlmSts/Pdg"));
        assertTrue(hasPath(facts, "/MtchgSts/Mtchd"));
        assertTrue(hasPath(facts, "/TxDtls/TradId"));
        assertTrue(hasPath(facts, "/TxDtls/XpctdSttlmDt"));
    }

    @Test
    void sese025EmitsConfirmationOperands() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("sese025-conf.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        List<Map<String, Object>> facts = facts(r.doc());
        assertTrue(hasPath(facts, "/TxIdDtls/AcctSvcrTxId"));
        assertTrue(hasPath(facts, "/QtyAndAcctDtls/SttldQty"));
        assertTrue(hasPath(facts, "/TradDtls/FctvSttlmDt"));
        assertTrue(hasPath(facts, "/TradDtls/UnqTxIdr"));
        assertTrue(hasPath(facts, "/SttldAmt/Amt"));
    }
}
