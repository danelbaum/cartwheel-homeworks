const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('analysis/review_app/app.js','utf8');
const ctx={esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};vm.createContext(ctx);
vm.runInContext(app.slice(app.indexOf('function structuredResult('),app.indexOf('function renderEvidence()')),ctx);
const render=(name,output)=>ctx.structuredResult({name,output});
let html=render('get_applicable_policies',{ok:true,order_id:9789,product_name:'Slim Fountain Pen',days_remaining:0,store_has_policy:false,deadline_semantics:{note:'Request vs receipt unspecified'},policy_references:[]});
for(const expected of ['9789','Slim Fountain Pen','Not recorded','>0<','>No<','Request vs receipt unspecified'])assert(html.includes(expected));
html=render('issue_refund',{ok:true,status:'queued_for_approval',amount_usd:102.5});assert(html.includes('queued_for_approval'));
html=render('get_applicable_policies',{ok:false,error:'permission_denied',reason:'Outside scope',order_id:9789});assert(html.includes('Outside scope'));assert(!html.includes('9789'));
assert(render('get_policy',{ok:true,title:'<script>',body:'<img src=x>'}).includes('&lt;img'));
assert(render('search_products',{ok:true,products:[],count:0}).includes('0 results'));
const root='analysis/state/',manifest=JSON.parse(fs.readFileSync(root+'sample_manifest.json')),sessions=new Set(manifest.samples.map(x=>x.session_id));
const traces=JSON.parse(fs.readFileSync(root+'review_app/live_traces.json')).traces;
let count=0;const names=new Set();for(const t of traces.filter(t=>sessions.has(t.session_id)))for(const tool of t.tools){assert(ctx.structuredResult(tool));names.add(tool.name);count++;}
console.log(`Passed structured evidence checks; rendered ${count} calls across ${names.size} tool types in initial batch.`);
