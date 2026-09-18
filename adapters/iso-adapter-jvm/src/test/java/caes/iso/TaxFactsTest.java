package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

/**
 * P14 — tax operands through the generic facts extractors.
 * Solo se verifica que el boundary JVM emite los facts fiscales que
 * la proyeccion Python consume; la semantica vive en el core.
 */
class TaxFactsTest {

    private static byte[] fixture(String name) throws IOException {
        try (InputStream in = TaxFactsTest.class
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
                        && qualifier.equals(f.get("source_qualifier")));
    }

    private static boolean hasPath(List<Map<String, Object>> facts,
            String needle) {
        return facts.stream().anyMatch(f ->
                String.valueOf(f.get("model_path")).contains(needle));
    }

    @Test
    void mt564EmitsTaxOperands() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt564-tax.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("MT564", doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasFact(facts, "92A", "TAXR"));
        assertTrue(hasFact(facts, "19B", "TAXR"));
        assertTrue(hasFact(facts, "19B", "NETT"));
        assertTrue(hasFact(facts, "19B", "GRSS"));
        assertTrue(hasFact(facts, "11A", "OPTN"));
        assertTrue(hasFact(facts, "22H", "CAOP"));
    }

    @Test
    void seev031EmitsTaxOperands() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("seev031-tax.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("seev.031.002.15",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasPath(facts, "/CshMvmntDtls"));
        assertTrue(hasPath(facts, "/WhldgTaxRate/Rate"));
        assertTrue(hasPath(facts, "/AmtDtls/WhldgTaxAmt"));
        assertTrue(hasPath(facts, "/AmtDtls/GrssAmt"));
        assertTrue(hasPath(facts, "/AmtDtls/NetAmt"));
        assertTrue(hasPath(facts, "/CtryOfIncmSrc"));
        assertTrue(hasPath(facts, "/IncmTp/Id"));
    }

    @Test
    void mt566EmitsActualTaxOperands() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt566-tax.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("MT566", doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasFact(facts, "92A", "TAXR"));
        assertTrue(hasFact(facts, "19B", "TAXR"));
        assertTrue(hasFact(facts, "19B", "NETT"));
        assertTrue(hasFact(facts, "19B", "GRSS"));
        assertTrue(hasFact(facts, "13A", "CAON"));
        assertTrue(hasFact(facts, "20C", "CORP"));
    }

    @Test
    void seev036EmitsActualTaxOperands() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("seev036-tax.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("seev.036.002.16",
                doc.get("message_identifier"));
        List<Map<String, Object>> facts = facts(doc);
        assertTrue(hasPath(facts, "/CshMvmntDtls"));
        assertTrue(hasPath(facts, "/AmtDtls/WhldgTaxAmt"));
        assertTrue(hasPath(facts, "/AmtDtls/GrssAmt"));
        assertTrue(hasPath(facts, "/AmtDtls/NetAmt"));
        assertTrue(hasPath(facts, "/CorpActnEvtId"));
    }
}
