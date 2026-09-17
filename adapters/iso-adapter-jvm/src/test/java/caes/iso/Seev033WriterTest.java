package caes.iso;

import static org.junit.jupiter.api.Assertions.*;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.prowidesoftware.swift.model.mx.MxSeev03300213;

class Seev033WriterTest {

    private static Map<String, Object> projection() {
        return Map.of(
                "schema", "CA_ES_SEEV033_PROJECTION_V1",
                "projection_status", "SERIALIZABLE",
                "envelope", Map.of(
                        "sender_bic", "BANKESMMAXX",
                        "receiver_bic", "BANKDEFFXXX",
                        "msg_def_idr", "seev.033.002.13",
                        "biz_svc", "swift.cbprplus.02",
                        "cre_dt", "2026-09-17T10:00:00Z",
                        "biz_msg_idr", "INS-0001"),
                "elements", List.of(
                        Map.of("model_path",
                                "CorpActnInstr/CorpActnGnlInf"
                                        + "/CorpActnEvtId",
                                "value", "SAN-DIV-2026"),
                        Map.of("model_path",
                                "CorpActnInstr/CorpActnGnlInf/EvtTp/Cd",
                                "value", "DVCA"),
                        Map.of("model_path",
                                "CorpActnInstr/CorpActnGnlInf"
                                        + "/UndrlygScty/FinInstrmId/ISIN",
                                "value", "ES0113900J37"),
                        Map.of("model_path",
                                "CorpActnInstr/AcctDtls/SfkpgAcct",
                                "value", "ACC-001"),
                        Map.of("model_path",
                                "CorpActnInstr/CorpActnInstr/OptnNb/Nb",
                                "value", "001"),
                        Map.of("model_path",
                                "CorpActnInstr/CorpActnInstr/OptnTp/Cd",
                                "value", "SECU"),
                        Map.of("model_path",
                                "CorpActnInstr/CorpActnInstr"
                                        + "/SctiesQtyOrInstdAmt"
                                        + "/SctiesQty/InstdQty/Qty/Unit",
                                "value", "12500")));
    }

    @Test
    void writesTypedXmlRoundTripsThroughModel() {
        IsoAdapter.Result r = Seev033Writer.run(projection());
        assertEquals(Seev033Writer.EXIT_OK, r.exitCode());
        Map<String, Object> doc = r.doc();
        assertEquals("CA_ES_SEEV033_XML_V1", doc.get("schema_version"));
        assertEquals("OK", doc.get("write_status"));
        assertEquals("seev.033.002.13", doc.get("message_identifier"));
        String xml = (String) doc.get("xml");
        assertNotNull(xml);
        assertNotNull(doc.get("xml_sha256"));
        assertNotNull(doc.get("source_projection_sha256"));

        // round-trip por el modelo tipado pinneado
        MxSeev03300213 mx = MxSeev03300213.parse(xml);
        assertNotNull(mx);
        assertEquals("seev.033.002.13", mx.getMxId().id());
        var instr = mx.getCorpActnInstr();
        assertEquals("SAN-DIV-2026",
                instr.getCorpActnGnlInf().getCorpActnEvtId());
        assertEquals("DVCA",
                instr.getCorpActnGnlInf().getEvtTp().getCd().name());
        assertEquals("ES0113900J37",
                instr.getCorpActnGnlInf().getUndrlygScty()
                        .getFinInstrmId().getISIN());
        assertEquals("ACC-001",
                instr.getAcctDtls().getSfkpgAcct());
        assertEquals("001",
                instr.getCorpActnInstr().getOptnNb().getNb());
        assertEquals("SECU",
                instr.getCorpActnInstr().getOptnTp().getCd().name());
        assertEquals(0,
                new java.math.BigDecimal("12500").compareTo(
                        instr.getCorpActnInstr().getSctiesQtyOrInstdAmt()
                                .getSctiesQty().getInstdQty().getQty()
                                .getUnit()));
        assertEquals("INS-0001", mx.getAppHdr().reference());
        assertEquals("BANKESMMAXX", mx.getAppHdr().from());
        assertEquals("BANKDEFFXXX", mx.getAppHdr().to());
    }

    @Test
    void deterministicXmlForSameInput() {
        String a = (String) Seev033Writer.run(projection())
                .doc().get("xml");
        String b = (String) Seev033Writer.run(projection())
                .doc().get("xml");
        assertEquals(a, b);
    }

    @Test
    void notSerializableIsRejected() {
        IsoAdapter.Result r = Seev033Writer.run(Map.of(
                "projection_status", "NOT_SERIALIZABLE",
                "reasons", List.of("INSTRUCTION_NOT_READY")));
        assertEquals(Seev033Writer.EXIT_NOT_SERIALIZABLE,
                r.exitCode());
        assertEquals("NOT_SERIALIZABLE", r.doc().get("write_status"));
        assertNull(r.doc().get("xml"));
    }

    @Test
    void garbageProjectionIsAdapterError() {
        IsoAdapter.Result r = Seev033Writer.run(Map.of(
                "projection_status", "SERIALIZABLE"));
        assertEquals(Seev033Writer.EXIT_ADAPTER_ERROR, r.exitCode());
        assertNull(r.doc().get("xml"));
    }
}
