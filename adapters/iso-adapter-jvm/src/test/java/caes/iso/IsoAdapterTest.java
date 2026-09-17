package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class IsoAdapterTest {

    private static byte[] fixture(String name) throws IOException {
        try (InputStream in = IsoAdapterTest.class
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

    @Test
    void mt564ValidProducesFactsWithProvenance() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt564-valid.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("OK", doc.get("parse_status"));
        assertEquals("MT564", doc.get("message_identifier"));
        assertEquals("CA_ES_SWIFT_MT_FACTS_V1", doc.get("schema_version"));
        assertEquals("ISO15022", doc.get("standard_family"));
        assertEquals("SRU2025", doc.get("standard_release"));
        assertEquals("prowide-core", doc.get("library"));
        assertEquals("SRU2025-10.3.19", doc.get("library_version"));
        assertNotNull(doc.get("adapter_version"));
        assertNotNull(doc.get("release_state_as_of"));

        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        String sha = (String) doc.get("input_sha256");
        assertNotNull(sha);
        assertEquals(64, sha.length());
        for (Map<String, Object> f : facts) {
            assertEquals("MT564", f.get("message_identifier"));
            assertNotNull(f.get("field_path"));
            assertNotNull(f.get("source_tag"));
            assertNotNull(f.get("sequence"));
            assertNotNull(f.get("evidence_locator"));
            assertEquals(sha, f.get("input_sha256"));
        }
        // spot-check: el qualifier CAEV/DVCA aparece como fact
        boolean caev = facts.stream().anyMatch(f ->
                "22F".equals(f.get("source_tag"))
                        && "CAEV".equals(f.get("source_qualifier"))
                        && "DVCA".equals(f.get("value")));
        assertTrue(caev, "esperaba fact 22F:CAEV//DVCA");
    }

    @Test
    void mt567ValidProducesLinkAndStatFacts() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt567-inst.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        assertEquals("MT567", r.doc().get("message_identifier"));
        List<Map<String, Object>> facts = facts(r.doc());
        boolean prev = facts.stream().anyMatch(f ->
                "20C".equals(f.get("source_tag"))
                        && "PREV".equals(f.get("source_qualifier"))
                        && "INS-0001".equals(f.get("value"))
                        && "GENL/LINK".equals(f.get("sequence")));
        boolean iprc = facts.stream().anyMatch(f ->
                "25D".equals(f.get("source_tag"))
                        && "IPRC".equals(f.get("source_qualifier"))
                        && "PACK".equals(f.get("value"))
                        && "GENL/STAT".equals(f.get("sequence")));
        boolean reas = facts.stream().anyMatch(f ->
                "GENL/STAT/REAS".equals(f.get("sequence")));
        assertTrue(prev, "esperaba fact LINK 20C::PREV//INS-0001");
        assertTrue(iprc, "esperaba fact STAT 25D::IPRC//PACK");
        assertTrue(reas, "esperaba facts en GENL/STAT/REAS");
    }

    @Test
    void mt566ValidProducesFacts() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt566-valid.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        assertEquals("MT566", r.doc().get("message_identifier"));
        assertFalse(facts(r.doc()).isEmpty());
    }

    @Test
    void mt566SecmoveProducesSequencedMovementFacts() throws Exception {
        // estructura oficial: CACONF > SECMOVE (repetitivo)
        IsoAdapter.Result r = IsoAdapter.run(
                fixture("mt566-secmove.fin"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        assertEquals("MT566", r.doc().get("message_identifier"));
        List<Map<String, Object>> facts = facts(r.doc());
        long secmoves = facts.stream().filter(f ->
                "CACONF/SECMOVE".equals(f.get("sequence"))
                        && "22H".equals(f.get("source_tag"))
                        && "CRDB".equals(f.get("source_qualifier")))
                .count();
        assertEquals(2, secmoves, "esperaba 2 SECMOVE con 22H::CRDB");
        boolean debt = facts.stream().anyMatch(f ->
                "CACONF/SECMOVE".equals(f.get("sequence"))
                        && "DEBT".equals(f.get("value")));
        boolean cred = facts.stream().anyMatch(f ->
                "CACONF/SECMOVE".equals(f.get("sequence"))
                        && "CRED".equals(f.get("value")));
        assertTrue(debt && cred, "esperaba CRDB//DEBT y CRDB//CRED");
        boolean psta = facts.stream().anyMatch(f ->
                "CACONF/SECMOVE".equals(f.get("sequence"))
                        && "36B".equals(f.get("source_tag"))
                        && "PSTA".equals(f.get("source_qualifier"))
                        && "125000,".equals(f.get("value")));
        assertTrue(psta, "esperaba 36B::PSTA//UNIT/125000,");
    }

    @Test
    void malformedIsParseErrorWithoutFinLeak() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("malformed.fin"));
        assertEquals(IsoAdapter.EXIT_PARSE_ERROR, r.exitCode());
        assertEquals("PARSE_ERROR", r.doc().get("parse_status"));
        String detail = String.valueOf(r.doc().get("detail"));
        String fin = new String(fixture("malformed.fin"),
                java.nio.charset.StandardCharsets.UTF_8);
        for (String line : fin.split("\n")) {
            if (!line.isBlank()) {
                assertFalse(detail.contains(line.trim()),
                        "detail filtra contenido FIN");
            }
        }
    }

    @Test
    void unsupportedTypeIsExplicit() throws Exception {
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt103.fin"));
        assertEquals(IsoAdapter.EXIT_UNSUPPORTED, r.exitCode());
        assertEquals("UNSUPPORTED_MESSAGE_TYPE",
                r.doc().get("parse_status"));
        assertEquals("MT103", r.doc().get("message_identifier"));
        assertTrue(facts(r.doc()).isEmpty());
    }

    @Test
    void deterministicExceptGeneratedAt() throws Exception {
        byte[] fin = fixture("mt564-valid.fin");
        Map<String, Object> a = IsoAdapter.run(fin).doc();
        Map<String, Object> b = IsoAdapter.run(fin).doc();
        a.remove("generated_at");
        b.remove("generated_at");
        assertEquals(a, b);
    }

    @Test
    void inputSha256IsCorrect() throws Exception {
        byte[] fin = fixture("mt564-valid.fin");
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(fin);
        StringBuilder sb = new StringBuilder();
        for (byte x : digest) {
            sb.append(String.format("%02x", x));
        }
        IsoAdapter.Result r = IsoAdapter.run(fin);
        assertEquals(sb.toString(), r.doc().get("input_sha256"));
    }

    @Test
    void repeatedQualifierFactsAreDistinguishable() throws Exception {
        // mt564 fixture tiene 98A::PAYD en CADETL y en CSMV
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt564-valid.fin"));
        long payd = facts(r.doc()).stream().filter(f ->
                "98A".equals(f.get("source_tag"))
                        && "PAYD".equals(f.get("source_qualifier")))
                .count();
        assertEquals(2, payd);
        List<String> locs = facts(r.doc()).stream()
                .filter(f -> "PAYD".equals(f.get("source_qualifier")))
                .map(f -> (String) f.get("evidence_locator"))
                .collect(java.util.stream.Collectors.toList());
        assertEquals(2, locs.stream().distinct().count());
    }

    @Test
    void missingOptionalFieldYieldsNoFact() throws Exception {
        // el fixture MT566 no lleva 70E en GENL; no debe aparecer
        IsoAdapter.Result r = IsoAdapter.run(fixture("mt566-valid.fin"));
        boolean t70 = facts(r.doc()).stream().anyMatch(f ->
                "70E".equals(f.get("source_tag")));
        assertFalse(t70);
    }
}
