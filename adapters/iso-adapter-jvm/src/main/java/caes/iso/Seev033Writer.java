package caes.iso;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.prowidesoftware.swift.model.mx.BusinessAppHdrV02;
import com.prowidesoftware.swift.model.mx.MxSeev03300213;
import com.prowidesoftware.swift.model.mx.dic.AccountAndBalance62;
import com.prowidesoftware.swift.model.mx.dic.BranchAndFinancialInstitutionIdentification6;
import com.prowidesoftware.swift.model.mx.dic.CorporateActionEventType119Choice;
import com.prowidesoftware.swift.model.mx.dic.CorporateActionEventType40Code;
import com.prowidesoftware.swift.model.mx.dic.CorporateActionGeneralInformation189;
import com.prowidesoftware.swift.model.mx.dic.CorporateActionInstruction002V13;
import com.prowidesoftware.swift.model.mx.dic.CorporateActionOption16Code;
import com.prowidesoftware.swift.model.mx.dic.CorporateActionOption243;
import com.prowidesoftware.swift.model.mx.dic.CorporateActionOption43Choice;
import com.prowidesoftware.swift.model.mx.dic.FinancialInstrumentAttributes133;
import com.prowidesoftware.swift.model.mx.dic.FinancialInstrumentQuantity36Choice;
import com.prowidesoftware.swift.model.mx.dic.FinancialInstitutionIdentification18;
import com.prowidesoftware.swift.model.mx.dic.OptionNumber1Choice;
import com.prowidesoftware.swift.model.mx.dic.Party44Choice;
import com.prowidesoftware.swift.model.mx.dic.Quantity55Choice;
import com.prowidesoftware.swift.model.mx.dic.SecuritiesOption88;
import com.prowidesoftware.swift.model.mx.dic.SecuritiesQuantityOrAmount7Choice;
import com.prowidesoftware.swift.model.mx.dic.SecurityIdentification20;

/**
 * P4.5 — seev.033.002.13 writer.
 *
 * CA_ES_SEEV033_PROJECTION_V1 (SERIALIZABLE) por stdin ->
 * modelo tipado Prowide -> CA_ES_SEEV033_XML_V1 por stdout.
 *
 * Solo materializa los elementos preregistrados en
 * docs/p4/p45-seev033-scope.md; el XML sale de mx.message() con
 * BusinessAppHdrV02 explicito (sin defaults).
 *
 * Exit codes: 0 OK, 2 NOT_SERIALIZABLE, 4 ADAPTER_ERROR.
 */
public final class Seev033Writer {

    static final String SCHEMA_VERSION = "CA_ES_SEEV033_XML_V1";
    static final int EXIT_OK = 0;
    static final int EXIT_NOT_SERIALIZABLE = 2;
    static final int EXIT_ADAPTER_ERROR = 4;

    private Seev033Writer() {
    }

    public static IsoAdapter.Result mainResult() {
        byte[] raw;
        try {
            raw = System.in.readAllBytes();
        } catch (IOException e) {
            return error(e.getClass().getSimpleName());
        }
        Map<String, Object> proj;
        try {
            proj = new ObjectMapper().readValue(raw, Map.class);
        } catch (Exception e) {
            return error(e.getClass().getSimpleName());
        }
        return run(proj);
    }

    @SuppressWarnings("unchecked")
    public static IsoAdapter.Result run(Map<String, Object> proj) {
        if (!"SERIALIZABLE".equals(proj.get("projection_status"))) {
            Map<String, Object> doc = envelope(
                    null, "NOT_SERIALIZABLE");
            doc.put("reasons", proj.getOrDefault("reasons",
                    List.of("PROJECTION_NOT_SERIALIZABLE")));
            return new IsoAdapter.Result(EXIT_NOT_SERIALIZABLE, doc);
        }
        try {
            Map<String, Object> env =
                    (Map<String, Object>) proj.get("envelope");
            List<Map<String, Object>> elements =
                    (List<Map<String, Object>>) proj.get("elements");
            Map<String, String> val = new LinkedHashMap<>();
            for (Map<String, Object> e : elements) {
                val.put(String.valueOf(e.get("model_path")),
                        String.valueOf(e.get("value")));
            }
            String xml = build(env, val);
            Map<String, Object> doc = envelope(
                    xml, "OK");
            doc.put("source_projection_sha256",
                    sha256hex(new ObjectMapper()
                            .writeValueAsBytes(proj)));
            doc.put("message_identifier", "seev.033.002.13");
            return new IsoAdapter.Result(EXIT_OK, doc);
        } catch (Throwable t) {
            return error(t.getClass().getSimpleName());
        }
    }

    private static IsoAdapter.Result error(String detail) {
        Map<String, Object> doc = envelope(null, "ADAPTER_ERROR");
        doc.put("detail", detail);
        return new IsoAdapter.Result(EXIT_ADAPTER_ERROR, doc);
    }

    private static Map<String, Object> envelope(
            String xml, String status) {
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("schema_version", SCHEMA_VERSION);
        doc.put("generated_at", Instant.now().toString());
        doc.put("write_status", status);
        doc.put("xml", xml);
        doc.put("xml_sha256",
                xml == null ? null
                        : sha256hex(xml.getBytes(StandardCharsets.UTF_8)));
        return doc;
    }

    /** Modelo tipado: solo los elementos del scope preregistrado. */
    static String build(Map<String, Object> env,
            Map<String, String> v) {
        CorporateActionInstruction002V13 doc =
                new CorporateActionInstruction002V13();

        CorporateActionGeneralInformation189 gnl =
                new CorporateActionGeneralInformation189();
        gnl.setCorpActnEvtId(v.get(
                "CorpActnInstr/CorpActnGnlInf/CorpActnEvtId"));
        CorporateActionEventType119Choice evtTp =
                new CorporateActionEventType119Choice();
        evtTp.setCd(CorporateActionEventType40Code.fromValue(
                v.get("CorpActnInstr/CorpActnGnlInf/EvtTp/Cd")));
        gnl.setEvtTp(evtTp);
        FinancialInstrumentAttributes133 und =
                new FinancialInstrumentAttributes133();
        SecurityIdentification20 sid = new SecurityIdentification20();
        sid.setISIN(v.get(
                "CorpActnInstr/CorpActnGnlInf/UndrlygScty"
                        + "/FinInstrmId/ISIN"));
        und.setFinInstrmId(sid);
        gnl.setUndrlygScty(und);
        doc.setCorpActnGnlInf(gnl);

        AccountAndBalance62 acct = new AccountAndBalance62();
        acct.setSfkpgAcct(v.get("CorpActnInstr/AcctDtls/SfkpgAcct"));
        doc.setAcctDtls(acct);

        CorporateActionOption243 instr = new CorporateActionOption243();
        OptionNumber1Choice nb = new OptionNumber1Choice();
        nb.setNb(v.get("CorpActnInstr/CorpActnInstr/OptnNb/Nb"));
        instr.setOptnNb(nb);
        CorporateActionOption43Choice tp =
                new CorporateActionOption43Choice();
        tp.setCd(CorporateActionOption16Code.fromValue(
                v.get("CorpActnInstr/CorpActnInstr/OptnTp/Cd")));
        instr.setOptnTp(tp);
        SecuritiesQuantityOrAmount7Choice qty =
                new SecuritiesQuantityOrAmount7Choice();
        SecuritiesOption88 sctiesQty = new SecuritiesOption88();
        Quantity55Choice instd = new Quantity55Choice();
        FinancialInstrumentQuantity36Choice unit =
                new FinancialInstrumentQuantity36Choice();
        unit.setUnit(new BigDecimal(v.get(
                "CorpActnInstr/CorpActnInstr/SctiesQtyOrInstdAmt"
                        + "/SctiesQty/InstdQty/Qty/Unit")));
        instd.setQty(unit);
        sctiesQty.setInstdQty(instd);
        qty.setSctiesQty(sctiesQty);
        instr.setSctiesQtyOrInstdAmt(qty);
        doc.setCorpActnInstr(instr);

        MxSeev03300213 mx = new MxSeev03300213();
        mx.setCorpActnInstr(doc);

        BusinessAppHdrV02 hdr = new BusinessAppHdrV02();
        hdr.setFr(party((String) env.get("sender_bic")));
        hdr.setTo(party((String) env.get("receiver_bic")));
        hdr.setBizMsgIdr((String) env.get("biz_msg_idr"));
        hdr.setMsgDefIdr((String) env.get("msg_def_idr"));
        hdr.setBizSvc((String) env.get("biz_svc"));
        hdr.setCreDt(OffsetDateTime.parse((String) env.get("cre_dt")));
        mx.setAppHdr(hdr);

        return mx.message();
    }

    private static Party44Choice party(String bic) {
        FinancialInstitutionIdentification18 fiid =
                new FinancialInstitutionIdentification18();
        fiid.setBICFI(bic);
        BranchAndFinancialInstitutionIdentification6 fi =
                new BranchAndFinancialInstitutionIdentification6();
        fi.setFinInstnId(fiid);
        Party44Choice p = new Party44Choice();
        p.setFIId(fi);
        return p;
    }

    private static String sha256hex(byte[] data) {
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder sb = new StringBuilder(d.length * 2);
            for (byte b : d) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            return null;
        }
    }
}
