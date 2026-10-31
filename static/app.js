const token=document.querySelector('meta[name="request-token"]').content;
const $=id=>document.getElementById(id);
const desktop=new URLSearchParams(location.search).get("desktop")==="1";
if(desktop)document.documentElement.classList.add("desktop");
const esc=s=>String(s??"");
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=esc(text);if(cls)n.className=cls;return n};
async function api(path,body){
  const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Request-Token":token},body:JSON.stringify(body)});
  if(path==="/api/export.csv"){if(!response.ok)throw Error("Export failed");return response.blob()}
  const data=await response.json();if(!response.ok)throw Error(data.error||"Request failed");return data;
}
let state=null,selectedPayment="",importText="",importPreview=null;
function money(amount,currency){return esc(amount)+" "+esc(currency)}
const isZeroAmount=value=>/^0(?:\.0+)?$/.test(String(value??""));
function payStatus(p){if(p.conflict)return["CONFLICT","conflict"];if(p.duplicate_fact)return["DUPLICATE FACT","conflict"];if(isZeroAmount(p.remaining_text))return["ALLOCATED","ok"];if(p.invoice_ref)return[!isZeroAmount(p.allocated_text)?"PARTIAL":"MATCH CANDIDATE",!isZeroAmount(p.allocated_text)?"ok":""];return["NEEDS REVIEW",""]}
function fact(label,value,detail){
  const d=node("div",undefined,"fact");d.append(node("span",label),node("strong",value||"—"));
  if(detail)d.append(node("code",detail));return d;
}
function renderBatches(){
  const box=$("batches");box.replaceChildren();
  if(!state.batches.length){box.append(node("div","No import receipts.","empty"));return}
  state.batches.forEach(b=>{const d=node("div",undefined,"batch");d.append(node("strong",b.source_name),node("span",b.record_type+" · "+b.row_count+" rows"),node("div",b.batch_id.slice(0,12)+"…"));box.append(d)});
}
function renderPayments(){
  const box=$("paymentList");box.replaceChildren();
  if(!state.payments.length){box.append(node("div","Import payment evidence to begin.","empty"));return}
  state.payments.forEach(p=>{
    const b=node("button",undefined,"payment-item"+(selectedPayment===p.row_key?" selected":""));b.type="button";b.dataset.row=p.row_key;
    const [label,klass]=payStatus(p);const badge=node("span",label,"pill "+klass);
    const id=node("span",p.record_id,"payment-id"),amount=node("span",money(p.amount_text,p.currency),"payment-amount");
    const sub=node("span",undefined,"payment-sub");sub.append(node("span",p.invoice_ref||"No invoice ID"),document.createTextNode(" · "),badge);
    b.append(id,amount,sub);b.onclick=()=>{selectedPayment=p.row_key;renderPayments();renderDetail()};box.append(b);
  });
}
function renderReceipts(){
  const counts=state.counts;
  $("batchCount").textContent=String(counts.batches).padStart(2,"0");
  $("invoiceCount").textContent=String(counts.invoices).padStart(2,"0");
  $("paymentCount").textContent=String(counts.payments).padStart(2,"0");
  $("paymentCountSide").textContent=String(counts.payments).padStart(2,"0");
  $("allocationCount").textContent=String(counts.allocations);
  $("openCount").textContent=String(state.payments.filter(p=>!isZeroAmount(p.remaining_text)||p.conflict).length);
  renderBatches();renderPayments();
}
function renderDetail(){
  const p=state.payments.find(x=>x.row_key===selectedPayment),rowMap=new Map([...state.payments,...state.invoices].map(r=>[r.row_key,r]));
  const conflictBox=$("conflicts");conflictBox.replaceChildren();
  if(state.conflicts.length){
    conflictBox.append(node("div","SOURCE CONFLICTS","eyebrow"));
    state.conflicts.forEach(c=>{const a=rowMap.get(c.left_row),b=rowMap.get(c.right_row),article=node("article",undefined,"conflict");
      article.append(node("strong",(a?.source_name||b?.source_name)+" · "+(a?.record_id||b?.record_id)),node("p",c.reason));
      article.append(node("p","Original: "+a?.amount_text+" "+a?.currency+" · batch "+a?.batch_id.slice(0,12)+"…"));
      article.append(node("p","Other row: "+b?.amount_text+" "+b?.currency+" · batch "+b?.batch_id.slice(0,12)+"…"));conflictBox.append(article)});
  }
  const allocations=$("allocationList");allocations.replaceChildren();
  if(!state.allocations.length)allocations.append(node("div","No allocations recorded. A suggestion changes no balances until you record it.","empty"));
  state.allocations.forEach(a=>{const pay=rowMap.get(a.payment_row),inv=rowMap.get(a.invoice_row),line=node("div",undefined,"allocation-row");
    const refs=node("span",undefined);refs.append(node("span",pay.record_id+" · row "+pay.row_number),node("br"),node("span","to "+inv.record_id+" · row "+inv.row_number));
    line.append(refs,node("code",money(a.amount_text,pay.currency)),node("small",a.reason));allocations.append(line)});
  const choice=$("invoiceChoice");choice.replaceChildren();
  if(!p){
    $("detailTitle").textContent="Select a payment row";$("detailStatus").textContent="READY";$("originalEvidence").replaceChildren(node("p","Choose a payment to inspect its source row.","muted"));
    choice.append(new Option("No payment selected",""));$("amountInput").value="";$("reasonInput").value="";$("allocate").disabled=true;return;
  }
  const [label,klass]=payStatus(p);$("detailTitle").textContent="Payment "+p.record_id;
  $("detailStatus").textContent=label;$("detailStatus").className="status-pill "+klass;
  const evidence=$("originalEvidence");evidence.replaceChildren(
    fact("SOURCE RECORD ID",p.record_id,"Source: "+p.source_name),
    fact("INVOICE REFERENCE",p.invoice_ref||"Not supplied","CSV row "+p.row_number+" · batch "+p.batch_id.slice(0,14)+"…"),
    fact("ORIGINAL AMOUNT",money(p.amount_text,p.currency),"Allocated "+p.allocated_text+" · remaining "+p.remaining_text),
    fact("SOURCE DATE",p.date_text||"Not supplied"),
    fact("RAW SOURCE ROW",p.raw_json));
  if(p.duplicate_fact)evidence.append(node("p","Repeated source facts stay visible for audit but cannot add allocation capacity.","warning"));
  const invoices=state.invoices.filter(i=>i.currency===p.currency&&!i.conflict&&!i.duplicate_fact&&!isZeroAmount(i.remaining_text));
  choice.append(new Option("Choose an invoice…",""));
  invoices.forEach(i=>choice.append(new Option(i.record_id+" · "+i.remaining_text+" "+i.currency+" remaining",i.row_key)));
  if(p.suggested_invoice_row)choice.value=p.suggested_invoice_row;
  $("amountInput").value=p.suggested_amount||p.remaining_text;
  $("allocate").disabled=p.conflict||p.duplicate_fact||isZeroAmount(p.remaining_text)||!invoices.length;
  if(p.allocations?.length){const d=fact("RECORDED SPLITS",p.allocations.map(a=>a.amount_text+" → "+a.invoice_id).join(" · "));evidence.append(d)}
}
async function refresh(){state=await api("/api/state");renderReceipts();renderDetail()}
function showError(target,error){target.textContent=error.message||String(error);target.classList.add("error-text")}
const importDialog=$("importDialog"),settingsDialog=$("settingsDialog");
$("importOpen").onclick=()=>{importDialog.showModal();$("previewResult").textContent="";$("mapping").replaceChildren();$("importSubmit").disabled=true};
$("settingsOpen").onclick=()=>settingsDialog.showModal();
document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>b.closest("dialog").close());
$("export").onclick=async()=>{try{const blob=await api("/api/export.csv"),url=URL.createObjectURL(blob),a=node("a");a.href=url;a.download="payment-matching-export.csv";a.click();URL.revokeObjectURL(url)}catch(e){alert(e.message)}};
$("csvFile").onchange=async e=>{const file=e.target.files[0];importPreview=null;$("importSubmit").disabled=true;$("mapping").replaceChildren();$("previewResult").textContent="";
  if(!file)return;if(file.size>1_000_000){$("previewResult").textContent="Choose a CSV under 1 MB.";return}
  importText=await file.text();if(!$("sourceName").value||$("sourceName").value==="bank-export")$("sourceName").value=file.name.replace(/\.csv$/i,"").slice(0,120);
};
function renderMapping(data){
  const box=$("mapping");box.replaceChildren();
  data.fields.forEach(field=>{const wrap=node("div",undefined,"map-field"),label=node("label",field.replace("_"," "));label.htmlFor="map-"+field;
    const select=node("select");select.id="map-"+field;select.dataset.field=field;select.append(new Option("Not mapped",""));
    data.headers.forEach(header=>select.append(new Option(header,header)));select.value=data.mapping[field]||"";wrap.append(label,select);box.append(wrap)});
  const preview=node("div",undefined,"preview-box"),table=node("table"),head=node("thead"),headRow=node("tr");
  const columns=["row_number","record_id","invoice_ref","amount_text","currency","date_text"];
  columns.forEach(col=>headRow.append(node("th",col)));head.append(headRow);table.append(head);
  const body=node("tbody");data.sample.forEach(row=>{const tr=node("tr");columns.forEach(col=>tr.append(node("td",row[col])));body.append(tr)});table.append(body);preview.append(table);box.append(preview);
}
$("preview").onclick=async()=>{const box=$("previewResult");box.textContent="Reading headers and rows…";box.classList.remove("error-text");
  try{if(!importText)throw Error("Choose a CSV file first.");importPreview=await api("/api/preview",{csv:importText,record_type:$("recordType").value,mapping:null});
    renderMapping(importPreview);box.textContent=String(importPreview.row_count)+" rows ready. IDs and amounts remain text.";$("importSubmit").disabled=false;
  }catch(e){showError(box,e);$("importSubmit").disabled=true}};
$("recordType").onchange=()=>{importPreview=null;$("importSubmit").disabled=true;$("mapping").replaceChildren()};
$("importForm").onsubmit=async e=>{e.preventDefault();const box=$("previewResult");box.classList.remove("error-text");
  try{if(!importPreview)throw Error("Preview the CSV before importing.");const mapping={};document.querySelectorAll("#mapping select[data-field]").forEach(s=>{if(s.value)mapping[s.dataset.field]=s.value});
    const result=await api("/api/import",{csv:importText,record_type:$("recordType").value,source_name:$("sourceName").value,mapping});
    box.replaceChildren();const receipt=node("div",undefined,"receipt "+(result.status==="duplicate"?"duplicate":""));
    receipt.append(node("span",result.message||("Imported "+result.row_count+" source rows.")),node("br"),node("span","Batch "+result.batch_id.slice(0,20)+"… · "+result.row_count+" rows · "+(result.conflict_count||0)+" conflicts"));box.append(receipt);
    $("importSubmit").disabled=true;selectedPayment="";await refresh();
  }catch(err){showError(box,err)}};
$("allocate").onclick=async()=>{const note=$("allocationFeedback");note.textContent="";note.classList.remove("error-text");
  try{const result=await api("/api/allocate",{payment_row:selectedPayment,invoice_row:$("invoiceChoice").value,amount_text:$("amountInput").value,reason:$("reasonInput").value});
    note.textContent=result.status==="duplicate"?result.message:"Recorded "+result.amount_text+". Source rows and reason are in the audit trail.";await refresh();
  }catch(e){showError(note,e)}};
let prefs={};
async function initializePreferences(){
  let saved=await api("/api/settings");
  if(!saved.saved){
    try{
      const legacy=JSON.parse(localStorage.getItem("workflow-ledger-prefs")||"null");
      if(legacy&&typeof legacy.compact==="boolean"&&typeof legacy.reduceMotion==="boolean"){
        saved=await api("/api/settings",{compact:legacy.compact,reduceMotion:legacy.reduceMotion});
        localStorage.removeItem("workflow-ledger-prefs");
      }
    }catch{}
  }
  prefs=saved.preferences||{compact:false,reduceMotion:false};
  $("compactToggle").checked=prefs.compact;$("motionToggle").checked=prefs.reduceMotion;
  document.body.classList.toggle("compact",prefs.compact);document.body.classList.toggle("reduce-motion",prefs.reduceMotion);
}
async function savePrefs(){
  const next={compact:$("compactToggle").checked,reduceMotion:$("motionToggle").checked};
  document.body.classList.toggle("compact",next.compact);document.body.classList.toggle("reduce-motion",next.reduceMotion);
  const status=$("prefsFeedback");status.textContent="Saving settings…";
  try{await api("/api/settings",next);status.textContent="Settings saved on this Mac."}
  catch(e){status.textContent=e.message;status.classList.add("error-text")}
}
$("compactToggle").onchange=savePrefs;
$("motionToggle").onchange=savePrefs;
const reduce=window.matchMedia("(prefers-reduced-motion: reduce)");if(reduce.matches)document.body.classList.add("reduce-motion");
Promise.all([refresh(),initializePreferences()]).catch(e=>{document.querySelector(".workbench").replaceChildren(node("div",e.message,"empty"))});
