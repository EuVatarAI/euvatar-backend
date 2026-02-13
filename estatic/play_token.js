import { Room, setLogLevel } from "https://cdn.skypack.dev/livekit-client";
setLogLevel("warn");

/* =================== CONFIG =================== */
const API = "http://127.0.0.1:5001";
const AVATAR_ID = "b53bf14741784d0d8f49edef2d74ef4e";
const SESSION_MIN = 2.5;
const AUTO_GREETING = false;
const GREETING_TEXT = "";
const IDLE_IMG = "https://images.unsplash.com/photo-1502989642968-94fbdc9eace4?q=80&w=1200&auto=format&fit=crop";
const CFG_KEY = "euv_cfg_vertical_card";
const CID_KEY = "euv_client_id";
const CLIENT_ID = (() => {
  const stored = localStorage.getItem(CID_KEY);
  if(stored) return stored;
  const gen = "cid_" + Math.random().toString(36).slice(2,9);
  localStorage.setItem(CID_KEY, gen);
  return gen;
})();

/* =================== STATE/DOM =================== */
let room=null, session_id=null, countdown=null, endAt=0, warned=false;
let totalPlannedSec=0;

const video=document.getElementById("vid");
const idle=document.getElementById("idle"), idlePoster=document.getElementById("idlePoster");
const btnTalk=document.getElementById("btnTalk"), btnEnd=document.getElementById("btnEnd"), btnMic=document.getElementById("btnMic");
const timer=document.getElementById("timer"), toast=document.getElementById("toast");
const statusEl=document.getElementById("status"), statusText=document.getElementById("statusText");
const badgeSession=document.getElementById("badgeSession"), badgeAvatar=document.getElementById("badgeAvatar");
const pillLang=document.getElementById("pillLang"), pillQuality=document.getElementById("pillQuality");

const ctxCard=document.getElementById("ctxCard"), ctxImg=document.getElementById("ctxImg");
let ctxTO=null; const CTX_TTL_MS=6500;

const displayName=document.getElementById("displayName");

const btnAdmin=document.getElementById("btnAdmin"), modAdm=document.getElementById("modAdm");
const cfgLang=document.getElementById("cfgLang"), cfgQuality=document.getElementById("cfgQuality");
const cfgAvatar=document.getElementById("cfgAvatar");

const cfgDisplayName=document.getElementById("cfgDisplayName"), cfgBackstory=document.getElementById("cfgBackstory");
const btnLogs=document.getElementById("btnLogs");
const btnAdmSave=document.getElementById("btnAdmSave"), btnAdmClose=document.getElementById("btnAdmClose");

const modExt=document.getElementById("modExt"), btnYes=document.getElementById("btnYes"), btnNo=document.getElementById("btnNo");
const onboarding=document.getElementById("onboarding"), btnOnbClose=document.getElementById("btnOnbClose");

// Contexto (upload/list)
const ctxAvatar=document.getElementById("ctxAvatar");
const ctxName=document.getElementById("ctxName");
const ctxKeywords=document.getElementById("ctxKeywords");
const ctxType=document.getElementById("ctxType");
const ctxFile=document.getElementById("ctxFile");
const btnCtxUpload=document.getElementById("btnCtxUpload");
const btnCtxList=document.getElementById("btnCtxList");
const ctxList=document.getElementById("ctxList");
// Training docs (upload/list)
const docAvatar=document.getElementById("docAvatar");
const docTitle=document.getElementById("docTitle");
const docFile=document.getElementById("docFile");
const btnDocUpload=document.getElementById("btnDocUpload");
const btnDocList=document.getElementById("btnDocList");
const docList=document.getElementById("docList");

/* =================== logger dev (opcional) =================== */
const dev=document.createElement('div'); dev.className='devlog'; dev.style.display='none'; document.body.appendChild(dev);
function addLog(k,m,v){const t=new Date().toTimeString().slice(0,8); dev.innerHTML+=`<span class=t>[${t}]</span> <span class=k>[${k}]</span> ${m?m:''}${v?` | <span class=v>${(typeof v==='string'?v:JSON.stringify(v))}</span>`:''}<br/>`; dev.scrollTop=dev.scrollHeight;}
function showDev(on=true){dev.style.display=on?'block':'none'; btnLogs.textContent=on?'Esconder logs':'Logs';}
showDev(false);

/* =================== utils =================== */
function fetchWithTimeout(url, opts={}, ms=12000){
  const controller=new AbortController(); const id=setTimeout(()=>controller.abort(),ms);
  const merged={...opts, signal:(opts.signal ?? controller.signal)};
  return fetch(url, merged).finally(()=>clearTimeout(id));
}
let hideStatusTO=null, toastTO=null;
function showStatus(text, cls=''){clearTimeout(hideStatusTO); statusEl.className='status show '+(cls||''); statusText.textContent=text;}
function hideStatus(delay=1200){clearTimeout(hideStatusTO); hideStatusTO=setTimeout(()=>statusEl.classList.remove("show"),delay);}
function toastMsg(t){clearTimeout(toastTO); toast.textContent=t; toast.classList.add("show"); toastTO=setTimeout(()=>toast.classList.remove('show'),2600);}
function mmss(sec){const m=String(Math.floor(sec/60)).padStart(2,"0"), s=String(Math.floor(sec%60)).padStart(2,"0"); return `${m}:${s}`}
function updateSessionBadges(active=false){
  if(!badgeSession) return;
  badgeSession.textContent = active ? "Sessão ativa" : "Sessão inativa";
  badgeSession.classList.toggle("live", active);
}
const AVATAR_NAMES = {
  "b53bf14741784d0d8f49edef2d74ef4e": "Marcelo (Padrão)",
  "Santa_Fireplace_Front_public": "Papai Noel 🎅"
};
function updateAvatarBadge(){
  if(!badgeAvatar) return;
  const id = cfgAvatar.value || AVATAR_ID;
  const name = AVATAR_NAMES[id] || id;
  badgeAvatar.textContent = `Avatar: ${name}`;
}
function updateLangQuality(){
  if(pillLang) pillLang.textContent = `Idioma: ${cfgLang.value||"pt-BR"}`;
  if(pillQuality) pillQuality.textContent = `Qualidade: ${cfgQuality.value||"low"}`;
}

/* =========== Contextos: upload + listagem =========== */
function ctxAvatarId(){ return (ctxAvatar.value||"").trim() || cfgAvatar.value || AVATAR_ID; }
function docAvatarId(){ return (docAvatar.value||"").trim() || cfgAvatar.value || AVATAR_ID; }
function currentAvatarId(){ return (cfgAvatar.value||AVATAR_ID); }

async function listContexts(){
  const avatar = ctxAvatarId();
  if(!avatar){ toastMsg("Informe o avatar_id."); return; }
  ctxList.textContent="Carregando…";
  try{
    const r = await fetchWithTimeout(`${API}/context/list?avatar_id=${encodeURIComponent(avatar)}`, {}, 10000);
    if(!r.ok){ ctxList.textContent=`Erro HTTP ${r.status}`; return; }
    const j = await r.json();
    if(!j.ok){ ctxList.textContent=j.error||"Erro"; return; }
    if(!j.items?.length){ ctxList.textContent="Nenhum contexto cadastrado."; return; }
    ctxList.innerHTML = j.items.map(it => {
      const kw = (it.keywords||"").trim();
      return `<div class="item">
        <div class="title">${it.name||"(sem nome)"}</div>
        <div class="meta">
          <span class="badge">${it.media_type||"image"}</span>
          ${kw ? `<span class="badge">kw: ${kw}</span>` : ""}
        </div>
        ${it.media_url ? `<a href="${it.media_url}" target="_blank" rel="noopener">abrir mídia</a>` : ""}
      </div>`;
    }).join("");
  }catch(e){
    ctxList.textContent="Erro ao listar: "+(e?.message||e);
  }
}

async function uploadContextMedia(){
  const avatar = ctxAvatarId();
  const name = (ctxName.value||"").trim();
  const keywords = (ctxKeywords.value||"").trim();
  const type = (ctxType.value||"image").trim();
  const file = ctxFile.files?.[0];
  if(!avatar || !name || !file){ toastMsg("Avatar, contexto e arquivo são obrigatórios."); return; }
  const fd = new FormData();
  fd.append("avatar_id", avatar);
  fd.append("contexto", name);
  fd.append("keywords", keywords);
  fd.append("media_type", type);
  fd.append("file", file, file.name);
  btnCtxUpload.disabled=true; btnCtxUpload.textContent="Enviando…";
  try{
    const r = await fetchWithTimeout(`${API}/upload/context-image`, { method:"POST", body:fd }, 20000);
    const j = await r.json();
    if(!r.ok || !j.ok){ toastMsg(j.error||`Erro HTTP ${r.status}`); return; }
    toastMsg("Contexto salvo.");
    listContexts();
    ctxFile.value="";
  }catch(e){
    toastMsg("Erro ao enviar: "+(e?.message||e));
  }finally{
    btnCtxUpload.disabled=false; btnCtxUpload.textContent="Subir mídia + keywords";
  }
}

async function listTrainingDocs(){
  const avatar = docAvatarId();
  if(!avatar){ toastMsg("Informe o avatar_id."); return; }
  docList.textContent="Carregando…";
  try{
    const r = await fetchWithTimeout(`${API}/training/list?avatar_id=${encodeURIComponent(avatar)}`, {}, 10000);
    if(!r.ok){ docList.textContent=`Erro HTTP ${r.status}`; return; }
    const j = await r.json();
    if(!j.ok){ docList.textContent=j.error||"Erro"; return; }
    if(!j.items?.length){ docList.textContent="Nenhum doc."; return; }
    docList.innerHTML = j.items.map(it => {
      return `<div class="item">
        <div class="title">${it.name||"(sem nome)"}</div>
        <div class="meta">${it.created_at ? `<span class="badge">${String(it.created_at).slice(0,10)}</span>` : ""}</div>
        ${it.url ? `<a href="${it.url}" target="_blank" rel="noopener">abrir documento</a>` : ""}
      </div>`;
    }).join("");
  }catch(e){
    docList.textContent="Erro ao listar: "+(e?.message||e);
  }
}

async function uploadTrainingDoc(){
  const avatar = docAvatarId();
  const title = (docTitle.value||"").trim();
  const file = docFile.files?.[0];
  if(!avatar || !file){ toastMsg("Avatar e arquivo são obrigatórios."); return; }
  const fd = new FormData();
  fd.append("avatar_id", avatar);
  fd.append("title", title);
  fd.append("file", file, file.name);
  btnDocUpload.disabled=true; btnDocUpload.textContent="Enviando…";
  try{
    const r = await fetchWithTimeout(`${API}/training/upload`, { method:"POST", body:fd }, 20000);
    const j = await r.json();
    if(!r.ok || !j.ok){ toastMsg(j.error||`Erro HTTP ${r.status}`); return; }
    toastMsg("Doc salvo.");
    listTrainingDocs();
    docFile.value="";
  }catch(e){
    toastMsg("Erro ao enviar: "+(e?.message||e));
  }finally{
    btnDocUpload.disabled=false; btnDocUpload.textContent="Subir doc";
  }
}

function aplicarModoPapaiNoel(avatarId) {
  const stage = document.querySelector(".stage");
  const vid = document.getElementById("vid");
  stage.classList.remove("stage-papai-noel");
  vid.classList.remove("video-papai-noel");
  if (avatarId === "Santa_Fireplace_Front_public") {
    stage.classList.add("stage-papai-noel");
    vid.classList.add("video-papai-noel");
    if (cfgQuality) {
      cfgQuality.value = "high";
      cfgQuality.setAttribute("disabled", "disabled");
      updateLangQuality();
    }
  } else if (cfgQuality) {
    cfgQuality.removeAttribute("disabled");
  }
}

/* =================== Config persistida =================== */
function applyDisplayName(name){
  const clean = (name||"").trim();
  if(clean){
    displayName.textContent=clean;
    displayName.classList.add('show');
  } else {
    displayName.textContent="";
    displayName.classList.remove('show');
  }
}

function loadCfg(){
  const s=JSON.parse(localStorage.getItem(CFG_KEY)||"{}");

  cfgLang.value = s.lang || "pt-BR";
  cfgQuality.value = s.quality || "low";
  cfgDisplayName.value = s.displayName || "";
  cfgBackstory.value = s.backstory || "";
  cfgAvatar.value = s.avatar || AVATAR_ID;
  ctxAvatar.value = cfgAvatar.value;
  docAvatar.value = cfgAvatar.value;

  applyDisplayName(s.displayName);
  updateAvatarBadge();
  updateLangQuality();
  updateSessionBadges(false);
  addLog('CFG','load', s);

  return {
    language: cfgLang.value,
    quality: cfgQuality.value,
    backstory: cfgBackstory.value.trim(),
    avatar: cfgAvatar.value
  };
}

function saveCfg(){
  const s={
    lang: cfgLang.value,
    quality: cfgQuality.value,
    displayName: cfgDisplayName.value.trim(),
    backstory: cfgBackstory.value.trim(),
    avatar: cfgAvatar.value
  };

  localStorage.setItem(CFG_KEY, JSON.stringify(s));
  applyDisplayName(s.displayName);
  addLog('CFG','save', s);
  updateAvatarBadge();
  updateLangQuality();
}

/* ========= Cartão de contexto (aparece e some) ========= */
function showCtxCard(url){
  if(!url) return hideCtxCard();
  ctxImg.src=url;
  ctxCard.classList.add('show');
  clearTimeout(ctxTO);
  ctxTO=setTimeout(hideCtxCard, CTX_TTL_MS);
}
function hideCtxCard(){
  ctxCard.classList.remove('show');
  clearTimeout(ctxTO);
}
ctxCard.addEventListener('click', hideCtxCard);

/* =================== /say contínuo (seu fluxo) =================== */
let SAY_BUSY=false;
const sayQueue=[];
let sayFailures=0; const SAY_FAIL_LIMIT=3;
let sayWatchdog=null;
let lastSayAt=0; const COOLDOWN_MS=1600;
let speakingUntil = 0;
const SPEAK_BUFFER_MS = 600;
const HARD_SAY_TIMEOUT_MS = 15000;

function startSayWatchdog(){ stopSayWatchdog(); sayWatchdog=setInterval(()=>{ if(SAY_BUSY){ addLog('SAY','watchdog releasing busy'); SAY_BUSY=false; } },6000); }
function stopSayWatchdog(){ if(sayWatchdog){ clearInterval(sayWatchdog); sayWatchdog=null; } }

function enqueueSay(text){
  if(!session_id||!text) return;
  const t=String(text).trim(); if(!t) return;
  sayQueue.push(t); addLog('SAY','enqueue', {len:sayQueue.length, text:t});
  drainSay();
}
async function drainSay(){
  if(SAY_BUSY || !session_id) return;
  SAY_BUSY=true; startSayWatchdog();
  try{
    while(sayQueue.length && session_id){
      const t=sayQueue.shift();

      const now = Date.now();
      const waitBusy = Math.max(0, speakingUntil - now);
      if(waitBusy>0){ addLog('SAY','aguardando fala terminar', waitBusy+'ms'); await new Promise(r=>setTimeout(r, waitBusy)); }

      const wait = Math.max(0, COOLDOWN_MS - (Date.now() - lastSayAt));
      if(wait>0) await new Promise(r=>setTimeout(r, wait));

      const ok = await doSay(t);
      if(!ok){
        sayFailures++;
        if(sayFailures>=SAY_FAIL_LIMIT){
          toastMsg("Falha ao enviar várias vezes. Pulei essa fala para continuar.");
          sayFailures=0;
        }else{
          await new Promise(r=>setTimeout(r, 450*sayFailures));
          sayQueue.unshift(t);
        }
      }else{
        sayFailures=0;
      }
    }
  } finally { SAY_BUSY=false; stopSayWatchdog(); }
}
async function doSay(text){
  for(let attempt=1; attempt<=4 && session_id; attempt++){
    try{
      showStatus(attempt===1?"Enviando…":"Reenviando…");

      const hardTO = setTimeout(async ()=>{
        const urlInt = `${API}/interrupt?client_id=${encodeURIComponent(CLIENT_ID)}`;
        try{ await fetchWithTimeout(urlInt,{method:"POST",headers:{"Content-Type":"application/json","X-Client-Id":CLIENT_ID},body:JSON.stringify({session_id, client_id: CLIENT_ID})}, 4000); }catch{}
      }, HARD_SAY_TIMEOUT_MS);

      const r=await fetchWithTimeout(`${API}/say?client_id=${encodeURIComponent(CLIENT_ID)}`,{
        method:"POST", headers:{"Content-Type":"application/json","X-Client-Id":CLIENT_ID},
        body:JSON.stringify({session_id,avatar_id:currentAvatarId(),text, client_id: CLIENT_ID})
      }, 15000);
      clearTimeout(hardTO);

      if(!r.ok){
        if(r.status===410){ toastMsg("Sessão encerrou. Toque em ‘Fale comigo’ para abrir outra."); return false; }
        if(r.status===429 || r.status===423){ await new Promise(res=>setTimeout(res, 1200*attempt)); continue; }
        if(r.status===502 || r.status===503){ await new Promise(res=>setTimeout(res, 700*attempt)); continue; }
        throw new Error(`say HTTP ${r.status}`);
      }

      const j=await r.json();
      console.log("MEDIA RECEBIDA:", j?.media || null);
      lastSayAt = Date.now();
      showStatus("Respondendo…"); hideStatus(1400);

      if(j?.duration_ms && Number.isFinite(j.duration_ms)){
        speakingUntil = Date.now() + j.duration_ms + SPEAK_BUFFER_MS;
      } else {
        speakingUntil = Date.now() + 8000;
      }

      if(j?.media?.type==="image" && j.media.url){
        showCtxCard(j.media.url);
        addLog('MEDIA','ctx card (auto-hide)', j.media.url);
      }

      addLog('SAY','ok', j);
      return true;
    }catch(e){
      addLog('ERR','doSay erro', String(e?.message||e));
      if(attempt===4){ showStatus("Erro ao enviar"); hideStatus(1600); }
    }
  }
  return false;
}

/* =================== timer + modal CONTINUAR =================== */
function startTimer(min){
  const total=Math.round(min*60); const start=Date.now()/1000; endAt=start+total; warned=false; clearInterval(countdown); totalPlannedSec=total;
  addLog('TIMER','start', {total_sec:total});
  countdown=setInterval(()=>{ 
    const now=Date.now()/1000; 
    const left=Math.max(0,endAt-now); 
    const elap=totalPlannedSec-left; 
    timer.textContent=`⏳ ${mmss(elap)} / ${mmss(totalPlannedSec)}`;
    if(left<=5 && !warned){ warned=true; modExt.classList.add("show"); }
    if(left<=0){
      clearInterval(countdown);
      modExt.classList.add("show");
      // não encerra automaticamente; aguarda escolha do usuário
    }
  },1000);
}

async function extendSessionTimer(){
  if(!session_id) return false;
  try{
    const r = await fetchWithTimeout(`${API}/keepalive?client_id=${encodeURIComponent(CLIENT_ID)}`,{
      method:"POST",
      headers:{"Content-Type":"application/json","X-Client-Id":CLIENT_ID},
      body:JSON.stringify({session_id, extend_minutes: SESSION_MIN, client_id: CLIENT_ID})
    }, 7000);
    const j = await r.json();
    if(j?.error_code === "session_inactive"){
      toastMsg("Sessão encerrou. Toque em ‘Fale comigo’ para abrir outra.");
      endSession();
      return false;
    }
    if(!j?.ok){
      toastMsg("Não foi possível estender a sessão agora.");
      return false;
    }
    addLog('TIMER','extended', {mins: SESSION_MIN});
    return true;
  }catch(e){
    addLog('ERR','extend_session', String(e?.message||e));
    toastMsg("Falha ao estender sessão.");
    return false;
  }
}

btnNo.onclick=()=>{ modExt.classList.remove("show"); endSession(); }
btnYes.onclick=async ()=>{ 
  const ok = await extendSessionTimer();
  if(!ok) return;
  modExt.classList.remove("show");
  startTimer(SESSION_MIN); // reinicia contagem completa alinhada com o backend
  showStatus("Sessão estendida"); hideStatus(1500); 
}

/* =================== fluxo =================== */
idlePoster.src = IDLE_IMG; loadCfg();
if(!localStorage.getItem("euv_onb_seen") && onboarding){
  onboarding.classList.add("show");
}
btnTalk.onclick=openSession;
btnEnd.onclick=endSession;

btnAdmin.onclick=()=>{modAdm.classList.add("show")};
btnAdmClose.onclick=()=>{modAdm.classList.remove('show')};
btnAdmSave.onclick=()=>{saveCfg(); modAdm.classList.remove('show'); toastMsg("Config salva.")};
btnCtxUpload.onclick=uploadContextMedia;
btnCtxList.onclick=listContexts;
btnDocUpload.onclick=uploadTrainingDoc;
btnDocList.onclick=listTrainingDocs;
btnLogs.onclick=()=>{ showDev(dev.style.display==='none'); };
if(btnOnbClose){ btnOnbClose.onclick=()=>{ onboarding.classList.remove("show"); localStorage.setItem("euv_onb_seen","1"); }; }

cfgAvatar.addEventListener("change", ()=>{
  ctxAvatar.value = cfgAvatar.value;
  docAvatar.value = cfgAvatar.value;
  updateAvatarBadge();
});

/* abrir sessão */
async function openSession(){
  if(session_id){
    toastMsg("Já existe uma sessão ativa.");
    return;
  }
  try{
    idle.classList.add("hidden");
    showStatus("Conectando…");
    const c=loadCfg();
    aplicarModoPapaiNoel(c.avatar);

    const r=await fetch(`${API}/new?`+new URLSearchParams({
      language:c.language, persona:"default", quality:c.quality, minutes:SESSION_MIN, backstory:c.backstory,avatar_id: c.avatar,
      client_id: CLIENT_ID
    }), { headers: { "X-Client-Id": CLIENT_ID }});
    const j=await r.json(); if(!j.ok) throw new Error(j.error||"Falha ao criar sessão");

    const room0=new Room();
    room0.on("trackSubscribed",(track)=>{
      if(track.kind==='video') track.attach(video);
      if(track.kind==='audio'){ const a=new Audio(); a.autoplay=true; a.playsInline=true; track.attach(a); document.body.appendChild(a); }
    });
    room0.on("connectionStateChanged",(state)=>{ addLog('LK','state', state); });
    await room0.connect(j.livekit_url, j.access_token);
    room=room0; session_id=j.session_id;

    btnEnd.classList.remove("hidden");
    btnMic.classList.remove("hidden");

    startTimer(SESSION_MIN);
    showStatus("Conectado"); hideStatus();
    updateSessionBadges(true);

    if(AUTO_GREETING && GREETING_TEXT) enqueueSay(GREETING_TEXT);
  }catch(e){
    showStatus("Erro na conexão"); hideStatus(2200);
    toastMsg("Erro: "+e.message);
    idle.classList.remove("hidden");
  }
}

/* encerrar sessão */
async function endSession(){
  try{ await fetch(`${API}/end?client_id=${encodeURIComponent(CLIENT_ID)}`,{method:"POST",headers:{"Content-Type":"application/json","X-Client-Id":CLIENT_ID},body:JSON.stringify({session_id, client_id: CLIENT_ID})}) }catch{}
  try{ if(room) await room.disconnect() }catch{}
  room=null; session_id=null; warned=false; clearInterval(countdown); timer.textContent="⏳ 00:00 / 00:00";
  hideCtxCard();
  btnEnd.classList.add("hidden"); btnMic.classList.add("hidden");
  idle.classList.remove("hidden");
  showStatus("Sessão encerrada"); hideStatus(1500);
  updateSessionBadges(false);
}

/* ===== VOZ (push-to-talk) ===== */
let recStream=null, mediaRec=null, recChunks=[], recActive=false;
btnMic.onclick=()=>{ if(!session_id){ toastMsg("Crie a sessão primeiro."); return; } if(!recActive) startRecordSTT(); else stopRecordSTT(); };

async function startRecordSTT(){
  if(!navigator.mediaDevices?.getUserMedia){ toastMsg("Sem permissão de microfone."); return; }
  try{
    recStream=await navigator.mediaDevices.getUserMedia({ audio:true });
    mediaRec=new MediaRecorder(recStream,{ mimeType:"audio/webm" });
    recChunks=[];
    mediaRec.ondataavailable=e=>{ if(e.data?.size) recChunks.push(e.data); };
    mediaRec.onstart=()=>{ recActive=true; btnMic.classList.add('rec'); statusEl.classList.add('rec'); showStatus("Gravando…","rec"); };
    mediaRec.onstop=async ()=>{
      const blob=new Blob(recChunks,{ type:"audio/webm" }); recChunks=[];
      try{
        showStatus("Transcrevendo…");
        const fd=new FormData(); fd.append("audio",blob,"audio.webm");
        const rr=await fetchWithTimeout(`${API}/stt?session_id=${encodeURIComponent(session_id)}&client_id=${encodeURIComponent(CLIENT_ID)}`,{method:"POST",headers:{"X-Client-Id":CLIENT_ID},body:fd}, 15000);
        const jj=await rr.json(); if(jj?.ok && jj.text){ enqueueSay(jj.text.trim()); } else { showStatus("Falhou transcrição"); hideStatus(1500); }
      }catch(e){ showStatus("Erro na transcrição"); hideStatus(1500); }
      finally{
        try{recStream.getTracks().forEach(t=>t.stop());}catch{}
        recActive=false; btnMic.classList.remove('rec'); statusEl.classList.remove('rec');
      }
    };
    mediaRec.start();
  }catch(e){ toastMsg("Não foi possível gravar áudio."); }
}
function stopRecordSTT(){ try{ if(mediaRec && recActive) mediaRec.stop(); }catch{} }
 
