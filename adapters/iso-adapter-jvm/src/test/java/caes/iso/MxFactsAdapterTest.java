package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class MxFactsAdapterTest {

    private static byte[] fixture(String name) throws IOException {
        try (InputStream in = MxFactsAdapterTest.class
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
    void seev031ProducesModelFacts() throws Exception {
        IsoAdapter.Result r = MxFactsAdapter.run(
                fixture("seev031-002.xml"));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("PARSE_OK", doc.get("parse_status"));
        assertEquals("seev.031.002.15",
                doc.get("message_identifier"));
        assertEquals("CA_ES_SWIFT_MX_FACTS_V1",
                doc.get("schema_version"));
        assertEquals("ISO20022", doc.get("standard_family"));
        assertEquals("prowide-iso20022", doc.get("library"));
        assertEquals("SRU2025-10.3.10", doc.get("library_version"));

        List<Map<String, Object>> facts = facts(doc);
        assertFalse(facts.isEmpty());
        String sha = (String) doc.get("input_sha256");
        for (Map<String, Object> f : facts) {
            assertEquals("seev.031.002.15",
                    f.get("message_identifier"));
            assertNotNull(f.get("model_path"));
            assertNotNull(f.get("evidence_locator"));
            assertNotNull(f.get("occurrence"));
            assertEquals(sha, f.get("input_sha256"));
        }
        boolean evtt = facts.stream().anyMatch(f ->
                f.get("model_path").equals(
                        "/Document/CorpActnNtfctn/CorpActnGnlInf"
                        + "/EvtTp/Cd")
                        && "DVCA".equals(f.get("value")));
        boolean isin = facts.stream().anyMatch(f ->
                ((String) f.get("model_path")).endsWith("ISIN")
                        && "ES0105448007".equals(f.get("value")));
        boolean ccy = facts.stream().anyMatch(f ->
                ((String) f.get("model_path")).endsWith("Amt/@Ccy")
                        && "EUR".equals(f.get("value")));
        boolean amt = facts.stream().anyMatch(f ->
                ((String) f.get("model_path")).endsWith(
                        "GrssDstrbtnRate/Amt")
                        && "0.25".equals(f.get("value")));
        assertTrue(evtt && isin && ccy && amt);
    }

    @Test
    void xxeIsRejectedWithoutExpansion() {
        String xxe = "<?xml version=\"1.0\"?>"
                + "<!DOCTYPE d [<!ENTITY x SYSTEM \"file:///etc/passwd\">]>"
                + "<Document xmlns=\"urn:iso:std:iso:20022:tech:xsd:"
                + "seev.031.002.15\"><CorpActnNtfctn><CorpActnGnlInf>"
                + "<CorpActnEvtId>&x;</CorpActnEvtId></CorpActnGnlInf>"
                + "</CorpActnNtfctn></Document>";
        IsoAdapter.Result r = MxFactsAdapter.run(
                xxe.getBytes(StandardCharsets.UTF_8));
        assertEquals(IsoAdapter.EXIT_PARSE_ERROR, r.exitCode());
        assertEquals("PARSE_ERROR", r.doc().get("parse_status"));
        String doc = r.doc().toString();
        assertFalse(doc.contains("root:"), "sin expansion XXE");
    }

    @Test
    void doctypeIsRejected() {
        String doc = "<?xml version=\"1.0\"?>"
                + "<!DOCTYPE Document>"
                + "<Document xmlns=\"urn:iso:std:iso:20022:tech:xsd:"
                + "seev.031.002.15\"><CorpActnNtfctn/></Document>";
        IsoAdapter.Result r = MxFactsAdapter.run(
                doc.getBytes(StandardCharsets.UTF_8));
        assertEquals(IsoAdapter.EXIT_PARSE_ERROR, r.exitCode());
    }

    @Test
    void malformedIsParseErrorWithoutXmlLeak() {
        String bad = "<Document xmlns=\"x\"><unclosed>";
        IsoAdapter.Result r = MxFactsAdapter.run(
                bad.getBytes(StandardCharsets.UTF_8));
        assertEquals(IsoAdapter.EXIT_PARSE_ERROR, r.exitCode());
        String detail = String.valueOf(r.doc().get("detail"));
        assertFalse(detail.contains("<unclosed"),
                "detail no filtra contenido XML");
    }

    @Test
    void unsupportedMessageIsExplicit() throws Exception {
        // camt.054 existe en el modelo pero no esta soportado en V1
        String camt = "<Document xmlns=\"urn:iso:std:iso:20022:tech:"
                + "xsd:camt.054.001.08\"><BkToCstmrDbtCdtNtfctn/>"
                + "</Document>";
        IsoAdapter.Result r = MxFactsAdapter.run(
                camt.getBytes(StandardCharsets.UTF_8));
        assertEquals(IsoAdapter.EXIT_UNSUPPORTED, r.exitCode());
        assertEquals("UNSUPPORTED_MESSAGE_TYPE",
                r.doc().get("parse_status"));
        assertEquals("camt.054.001.08",
                r.doc().get("message_identifier"));
    }

    @Test
    void seev031Variant001AlsoReads() {
        String doc = "<Document xmlns=\"urn:iso:std:iso:20022:tech:"
                + "xsd:seev.031.001.15\"><CorpActnNtfctn>"
                + "<CorpActnGnlInf><CorpActnEvtId>E1</CorpActnEvtId>"
                + "</CorpActnGnlInf></CorpActnNtfctn></Document>";
        IsoAdapter.Result r = MxFactsAdapter.run(
                doc.getBytes(StandardCharsets.UTF_8));
        assertEquals(IsoAdapter.EXIT_OK, r.exitCode());
        assertEquals("seev.031.001.15",
                r.doc().get("message_identifier"));
    }

    @Test
    void emptyAndOversizedFailClosed() {
        IsoAdapter.Result e = MxFactsAdapter.run(new byte[0]);
        assertEquals(IsoAdapter.EXIT_PARSE_ERROR, e.exitCode());
        assertEquals("EMPTY_INPUT", e.doc().get("detail"));
        byte[] big = new byte[MxFactsAdapter.MAX_INPUT_BYTES + 1];
        IsoAdapter.Result b = MxFactsAdapter.run(big);
        assertEquals(IsoAdapter.EXIT_PARSE_ERROR, b.exitCode());
        assertEquals("INPUT_TOO_LARGE", b.doc().get("detail"));
    }

    @Test
    void deterministicExceptGeneratedAt() throws Exception {
        byte[] xml = fixture("seev031-002.xml");
        Map<String, Object> a = MxFactsAdapter.run(xml).doc();
        Map<String, Object> b = MxFactsAdapter.run(xml).doc();
        a.remove("generated_at");
        b.remove("generated_at");
        assertEquals(a, b);
    }

    @Test
    void inputSha256IsCorrect() throws Exception {
        byte[] xml = fixture("seev031-002.xml");
        byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest(xml);
        StringBuilder sb = new StringBuilder();
        for (byte x : digest) {
            sb.append(String.format("%02x", x));
        }
        IsoAdapter.Result r = MxFactsAdapter.run(xml);
        assertEquals(sb.toString(), r.doc().get("input_sha256"));
    }
}
