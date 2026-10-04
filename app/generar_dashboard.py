"""
Genera el dashboard: un único archivo HTML autocontenido.

Decisión de diseño: los datos van embebidos en el HTML, no cargados por fetch.
Así el dashboard funciona con doble clic desde el disco (file://) sin servidor
ni CORS. Se abre y funciona, hoy y dentro de seis meses.

Las areas y la zona salen de la configuracion activa (`areas.py`) al generar,
y el nombre, de `perfil.CANDIDATO`.

El seguimiento de postulaciones vive en localStorage del navegador, así que
marcar "ya apliqué" sobrevive a que se regenere el dashboard.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

import areas
from nucleo import DATOS, cargar_json, log
from perfil import CANDIDATO

SALIDA = Path(__file__).resolve().parent.parent / "dashboard.html"

PLANTILLA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ULTRA CHAMBA — Panel de vacantes</title>
<style>
:root{
  --bg:#0b0f17; --bg2:#121826; --bg3:#1a2233; --linea:#243049;
  --txt:#e6edf7; --txt2:#98a6bf; --txt3:#64748b;
  --acento:#4f9cf9; --ok:#34d399; --warn:#fbbf24; --mal:#f87171;
  --oro:#f5b942; --violeta:#a78bfa;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;padding:0 0 60px}
a{color:var(--acento);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1400px;margin:0 auto;padding:0 20px}

header{background:linear-gradient(160deg,#131c2e,#0b0f17);border-bottom:1px solid var(--linea);padding:26px 0 22px;margin-bottom:22px}
h1{font-size:26px;letter-spacing:-.5px;display:flex;align-items:center;gap:10px}
h1 .chip{font-size:11px;font-weight:600;background:var(--acento);color:#08121f;padding:3px 9px;border-radius:20px;letter-spacing:.4px}
.sub{color:var(--txt2);font-size:13.5px;margin-top:7px}

.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:11px;margin-top:20px}
.stat{background:var(--bg2);border:1px solid var(--linea);border-radius:11px;padding:13px 15px}
.stat .n{font-size:25px;font-weight:700;line-height:1.15}
.stat .l{font-size:11px;color:var(--txt2);text-transform:uppercase;letter-spacing:.6px;margin-top:3px}

.barra{background:var(--bg2);border:1px solid var(--linea);border-radius:12px;padding:14px 16px;margin-bottom:18px;position:sticky;top:0;z-index:20;backdrop-filter:blur(8px)}
.fila{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.fila+.fila{margin-top:10px}
input[type=search]{flex:1;min-width:230px;background:var(--bg3);border:1px solid var(--linea);color:var(--txt);padding:9px 13px;border-radius:8px;font-size:14px}
input[type=search]:focus{outline:none;border-color:var(--acento)}
.et{font-size:11px;color:var(--txt3);text-transform:uppercase;letter-spacing:.7px;margin-right:2px;font-weight:600}
button.f{background:var(--bg3);border:1px solid var(--linea);color:var(--txt2);padding:6px 12px;border-radius:7px;cursor:pointer;font-size:12.5px;transition:.12s}
button.f:hover{border-color:var(--acento);color:var(--txt)}
button.f.on{background:var(--acento);border-color:var(--acento);color:#08121f;font-weight:600}
select{background:var(--bg3);border:1px solid var(--linea);color:var(--txt);padding:7px 10px;border-radius:7px;font-size:13px}

.conteo{color:var(--txt2);font-size:13px;margin:0 0 12px 2px}
.conteo b{color:var(--txt)}

.tarjeta{background:var(--bg2);border:1px solid var(--linea);border-radius:12px;padding:16px 18px;margin-bottom:11px;transition:.13s}
.tarjeta:hover{border-color:#31405f;transform:translateY(-1px)}
.tarjeta.aplicado{opacity:.5}
.tarjeta.aplicado .tit{text-decoration:line-through}
.cab{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
.tit{font-size:16.5px;font-weight:650;letter-spacing:-.2px}
.emp{color:var(--txt2);font-size:13.5px;margin-top:3px}
.emp b{color:#c7d4e8;font-weight:600}
.score{text-align:center;flex-shrink:0;min-width:62px}
.score .v{font-size:23px;font-weight:750;line-height:1}
.score .t{font-size:9.5px;color:var(--txt3);text-transform:uppercase;letter-spacing:.7px;margin-top:2px}

.etiquetas{display:flex;gap:6px;flex-wrap:wrap;margin-top:11px}
.tag{font-size:11px;padding:3px 9px;border-radius:20px;background:var(--bg3);color:var(--txt2);border:1px solid var(--linea);white-space:nowrap}
.tag.ok{background:rgba(52,211,153,.13);color:var(--ok);border-color:rgba(52,211,153,.3)}
.tag.warn{background:rgba(251,191,36,.13);color:var(--warn);border-color:rgba(251,191,36,.3)}
.tag.mal{background:rgba(248,113,113,.13);color:var(--mal);border-color:rgba(248,113,113,.3)}
.tag.oro{background:rgba(245,185,66,.15);color:var(--oro);border-color:rgba(245,185,66,.35);font-weight:600}
.tag.vio{background:rgba(167,139,250,.13);color:var(--violeta);border-color:rgba(167,139,250,.3)}
.tag.skill{background:rgba(79,156,249,.1);color:#8fbdfb;border-color:rgba(79,156,249,.25)}

.acc{display:flex;gap:9px;margin-top:13px;align-items:center;flex-wrap:wrap}
.btn{background:var(--acento);color:#08121f;padding:7px 15px;border-radius:7px;font-size:13px;font-weight:600;border:none;cursor:pointer}
.btn:hover{filter:brightness(1.12);text-decoration:none}
.btn.sec{background:transparent;color:var(--txt2);border:1px solid var(--linea)}
.btn.sec:hover{border-color:var(--acento);color:var(--txt)}
.btn.marc{background:transparent;color:var(--ok);border:1px solid rgba(52,211,153,.35)}

details{margin-top:11px}
summary{cursor:pointer;color:var(--txt3);font-size:12.5px;list-style:none;user-select:none}
summary::-webkit-details-marker{display:none}
summary:before{content:"▸ ";color:var(--acento)}
details[open] summary:before{content:"▾ "}
.porque{margin-top:9px;padding:11px 13px;background:var(--bg);border-radius:8px;border-left:2px solid var(--acento);font-size:12.5px;color:var(--txt2)}
.porque li{margin:3px 0 3px 16px}
.desc{margin-top:9px;font-size:12.5px;color:var(--txt3);max-height:150px;overflow:auto;padding:9px 12px;background:var(--bg);border-radius:8px;line-height:1.6}
.vacio{text-align:center;padding:60px 20px;color:var(--txt3)}
.pie{text-align:center;color:var(--txt3);font-size:12px;margin-top:34px;padding-top:20px;border-top:1px solid var(--linea)}
mark{background:rgba(245,185,66,.3);color:inherit;border-radius:2px}
@media(max-width:640px){.cab{flex-direction:column}.score{text-align:left}}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>ULTRA CHAMBA <span class="chip">VERIFICADO</span></h1>
  <div class="sub">Panel de vacantes de <b>__NOMBRE__</b> · __AREAS__ · prácticas y nivel inicial · __SUB_ZONA__<br>
  Última actualización: __FECHA__</div>
  <div class="stats" id="stats"></div>
</div></header>

<div class="wrap">
  <div class="barra">
    <div class="fila">
      <input type="search" id="buscar" placeholder="Buscar por puesto, empresa, tecnología, ciudad...">
      <select id="orden">
        <option value="score">Ordenar: mejor fit</option>
        <option value="fecha">Ordenar: más reciente</option>
        <option value="empresa">Ordenar: empresa (A-Z)</option>
      </select>
    </div>
    <div class="fila"><span class="et">Prioridad</span><span id="f-veredicto"></span></div>
    <div class="fila"><span class="et">Área</span><span id="f-area"></span></div>
    <div class="fila"><span class="et">Nivel</span><span id="f-nivel"></span></div>
    <div class="fila"><span class="et">Modalidad</span><span id="f-modalidad"></span></div>
    <div class="fila"><span class="et">Ubicación</span><span id="f-ubic"></span></div>
    <div class="fila"><span class="et">Experiencia</span><span id="f-exp"></span></div>
    <div class="fila"><span class="et">Verificación</span><span id="f-verif"></span>
      <span style="flex:1"></span>
      <button class="f" id="ocultar-aplicadas">Ocultar aplicadas</button>
      <button class="f" id="limpiar">Limpiar filtros</button>
    </div>
  </div>
  <div class="conteo" id="conteo"></div>
  <div id="lista"></div>
  <div class="pie">
    ULTRA CHAMBA · generado por el pipeline local · los datos salen de las bolsas oficiales de cada empresa y de bolsas de empleo públicas<br>
    Tu progreso (aplicadas) se guarda en este navegador y sobrevive a que se regenere el panel.
  </div>
</div>

<script>
const DATOS = __DATOS__;
const ESTADS = __ESTADS__;

const K='ultrachamba.aplicadas';
let aplicadas = new Set(JSON.parse(localStorage.getItem(K)||'[]'));
const guardar = () => localStorage.setItem(K, JSON.stringify([...aplicadas]));

const filtros = {veredicto:new Set(), area:new Set(), nivel:new Set(), modalidad:new Set(),
                 ubic:new Set(), exp:new Set(), verif:new Set()};
let ocultarAplicadas = false;

const ETIQ = {
  veredicto:{'aplicar-ya':'Aplicar ya','buen-fit':'Buen fit','explorar':'Explorar','zona-gris':'Zona gris (confirmar)'},
  area:__ETIQ_AREA__,
  nivel:{'practicas':'Prácticas','junior':'Junior','medio':'Medio'},
  modalidad:{'remoto':'Remoto','presencial':'Presencial','hibrido':'Híbrido'},
  ubic:{'en-zona':'En __ZONA_CORTA__ (sin mudanza)','exige-mudarse':'Exige mudarse'},
  exp:{'sin-experiencia':'Alcanzable sin experiencia','pide-anios':'Pide años que no tienes'},
  verif:{'viva':'Viva','sin-verificar':'Sin verificar','inaccesible':'Inaccesible'}
};

// Campos derivados: los filtros de ubicación y experiencia no son campos
// planos del dato, se calculan aquí para que el filtrado sea uniforme.
// La zona base sale de ULTRACHAMBA_ZONA al generar. Sin zona base (`nacional`)
// es null y nada se marca como "en tu zona".
const RX_ZONA = __RX_ZONA__;
const enZona = u => !!(RX_ZONA && RX_ZONA.test(u||''));
function derivado(v, campo){
  if(campo==='verif') return v.verificacion.estado;
  if(campo==='ubic'){
    if(enZona(v.ubicacion)) return 'en-zona';
    if(v.requiere_mudanza) return 'exige-mudarse';
    return '';
  }
  if(campo==='exp') return (v.anios_exigidos && v.anios_exigidos>=3) ? 'pide-anios' : 'sin-experiencia';
  return v[campo];
}

function pintarStats(){
  // Las dos primeras salian de ESTADS (o sea, de `estadisticas.json`) y las
  // demas de DATOS. Por eso el 27-ago-2026 este recuadro decia "2.228 vacantes
  // vivas" el mismo dia en que el panel decia 3.700: ese 2.228 era
  // `corridas.guardadas` de la ultima corrida publicado bajo el rotulo
  // `vivas`, y el 133.579 de "Analizadas" no lo respalda nadie
  // (`corridas.crudas` es NULL en las 11 corridas).
  //
  // Ahora TODAS se cuentan sobre DATOS, que es `vacantes.json`, generado
  // desde la base en la misma corrida. La regla del proyecto, aplicada al
  // sitio que se abre primero: si una cifra no sale de la base, es un
  // bug. Van juntas ademas por una razon practica: contadas todas sobre la
  // misma lista, no pueden contradecirse entre ellas.
  const s = [
    ['vivas', DATOS.length, 'Vacantes vivas'],
    ['ya', DATOS.filter(v=>v.veredicto==='aplicar-ya').length, 'Aplicar ya'],
    ['pract', DATOS.filter(v=>v.nivel==='practicas').length, 'Prácticas'],
    ['mty', RX_ZONA ? DATOS.filter(v=>enZona(v.ubicacion)).length : '—', '__ETIQ_ZONA__'],
    ['rem', DATOS.filter(v=>v.modalidad==='remoto').length, 'Remotas'],
    ['mud', DATOS.filter(v=>v.requiere_mudanza).length, 'Exigen mudarse'],
    ['aplic', DATOS.filter(v=>v.aplicada).length, 'Ya postuladas'],
  ];
  document.getElementById('stats').innerHTML = s.map(([k,n,l])=>
    `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
}

function pintarFiltros(){
  const conf = [
    ['f-veredicto','veredicto',['aplicar-ya','buen-fit','explorar','zona-gris']],
    ['f-area','area',__VALORES_AREA__],
    ['f-nivel','nivel',['practicas','junior','medio']],
    ['f-modalidad','modalidad',['remoto','presencial','hibrido']],
    ['f-ubic','ubic',['en-zona','exige-mudarse']],
    ['f-exp','exp',['sin-experiencia','pide-anios']],
    ['f-verif','verif',['viva','sin-verificar','inaccesible']],
  ];
  for(const [id,campo,vals] of conf){
    const cont=document.getElementById(id);
    // Si falta el contenedor, se omite ese filtro en vez de romper el render
    // completo: un fallo de un filtro no debe dejar el panel en blanco.
    if(!cont) continue;
    cont.innerHTML='';
    for(const v of vals){
      const n = DATOS.filter(d => derivado(d, campo)===v).length;
      if(!n) continue;
      const b=document.createElement('button');
      b.className='f'; b.textContent=`${ETIQ[campo][v]||v} (${n})`;
      b.onclick=()=>{filtros[campo].has(v)?filtros[campo].delete(v):filtros[campo].add(v);
        b.classList.toggle('on'); render();};
      cont.appendChild(b);
    }
  }
}

function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

function colorScore(s){ return s>=72?'var(--ok)': s>=56?'var(--oro)': s>=40?'var(--warn)':'var(--txt3)'; }

function tarjeta(v){
  const ap = aplicadas.has(v.id);
  const ve = v.verificacion||{};
  const tagVerif = ve.estado==='viva'
    ? `<span class="tag ok" title="${esc(ve.detalle)}">✓ verificada viva</span>`
    : ve.estado==='sin-verificar'
      ? `<span class="tag warn" title="${esc(ve.detalle)}">? sin confirmar</span>`
      : `<span class="tag mal" title="${esc(ve.detalle)}">! ${esc(ve.estado)}</span>`;

  const enMty = enZona(v.ubicacion);

  return `<div class="tarjeta ${ap?'aplicado':''}" data-id="${v.id}">
    <div class="cab">
      <div style="flex:1;min-width:0">
        <div class="tit">${esc(v.titulo)}</div>
        <div class="emp"><b>${esc(v.empresa)}</b> · ${esc(v.ubicacion||'sin ubicación')}${v.salario?' · '+esc(v.salario):''}</div>
      </div>
      <div class="score"><div class="v" style="color:${colorScore(v.score)}">${v.score}</div><div class="t">fit</div></div>
    </div>
    <div class="etiquetas">
      ${v.veredicto==='aplicar-ya'?'<span class="tag oro">★ aplicar ya</span>':''}
      ${v.veredicto==='zona-gris'?'<span class="tag warn">zona gris — pregunta si contratan desde México</span>':''}
      ${v.nivel==='practicas'?'<span class="tag vio">prácticas</span>':v.nivel==='junior'?'<span class="tag vio">junior</span>':''}
      <span class="tag">${esc(ETIQ.area[v.area]||v.area)}</span>
      <span class="tag">${esc(ETIQ.modalidad[v.modalidad]||v.modalidad)}</span>
      ${enMty?'<span class="tag ok">__ZONA_CORTA__ — sin mudanza</span>':''}
      ${v.requiere_mudanza?`<span class="tag mal" title="Presencial o híbrido fuera de tu zona base">exige mudarse a ${esc((v.ubicacion||'').split(',').slice(-2).join(',').trim())}</span>`:''}
      ${v.anios_exigidos>=3?`<span class="tag mal" title="${esc(v.evidencia_experiencia||'')}">pide ${v.anios_exigidos}+ años de experiencia</span>`:''}
      ${v.anios_exigidos!=null&&v.anios_exigidos<3?'<span class="tag ok">alcanzable sin experiencia</span>':''}
      ${tagVerif}
      ${v.dias_publicada!=null && v.dias_publicada<=7?`<span class="tag ok">nueva (${v.dias_publicada}d)</span>`:''}
      <span class="tag">${esc((v.fuente||'').split(':')[0])}</span>
      ${(v.habilidades_coincidentes||[]).slice(0,5).map(h=>`<span class="tag skill">${esc(h)}</span>`).join('')}
    </div>
    <div class="acc">
      <a class="btn" href="${esc(v.url)}" target="_blank" rel="noopener">Ver y postular →</a>
      <button class="btn marc" onclick="marcar('${v.id}')">${ap?'✓ aplicada — deshacer':'Marcar como aplicada'}</button>
      <button class="btn sec" onclick="copiar('${v.id}')">Copiar datos</button>
    </div>
    <details>
      <summary>Por qué el sistema te la recomienda (${(v.motivos||[]).length} razones)</summary>
      <div class="porque"><ul>${(v.motivos||[]).map(m=>`<li>${esc(m)}</li>`).join('')}</ul></div>
      ${v.descripcion?`<div class="desc">${esc(v.descripcion.slice(0,1400))}…</div>`:''}
    </details>
  </div>`;
}

function render(){
  const q = document.getElementById('buscar').value.toLowerCase().trim();
  let lista = DATOS.filter(v=>{
    for(const [campo,set] of Object.entries(filtros)){
      if(!set.size) continue;
      if(!set.has(derivado(v, campo))) return false;
    }
    if(ocultarAplicadas && aplicadas.has(v.id)) return false;
    if(q){
      const blob = `${v.titulo} ${v.empresa} ${v.ubicacion} ${(v.habilidades_coincidentes||[]).join(' ')} ${v.descripcion||''}`.toLowerCase();
      if(!blob.includes(q)) return false;
    }
    return true;
  });

  const orden = document.getElementById('orden').value;
  if(orden==='score') lista.sort((a,b)=>b.score-a.score);
  if(orden==='fecha') lista.sort((a,b)=>(b.publicado||'').localeCompare(a.publicado||''));
  if(orden==='empresa') lista.sort((a,b)=>a.empresa.localeCompare(b.empresa));

  document.getElementById('conteo').innerHTML =
    `Mostrando <b>${lista.length}</b> de <b>${DATOS.length}</b> vacantes · <b>${aplicadas.size}</b> marcadas como aplicadas`;
  document.getElementById('lista').innerHTML =
    lista.length ? lista.map(tarjeta).join('') :
    '<div class="vacio">Ningún resultado con esos filtros.<br>Prueba quitando alguno.</div>';
}

window.marcar = id => { aplicadas.has(id)?aplicadas.delete(id):aplicadas.add(id); guardar(); render(); };
window.copiar = id => {
  const v = DATOS.find(x=>x.id===id);
  const txt = `${v.titulo}\\n${v.empresa}\\n${v.ubicacion}\\n${v.url}\\nFit: ${v.score}/100 (${v.veredicto})`;
  navigator.clipboard.writeText(txt);
};

document.getElementById('buscar').oninput = render;
document.getElementById('orden').onchange = render;
document.getElementById('limpiar').onclick = () => {
  Object.values(filtros).forEach(s=>s.clear());
  document.querySelectorAll('button.f.on').forEach(b=>b.classList.remove('on'));
  document.getElementById('buscar').value=''; render();
};
document.getElementById('ocultar-aplicadas').onclick = e => {
  ocultarAplicadas = !ocultarAplicadas; e.target.classList.toggle('on'); render();
};

pintarStats(); pintarFiltros(); render();
</script>
</body></html>
"""


def generar() -> Path:
    vacantes = cargar_json("vacantes.json", [])
    # `estadisticas.json` ya NO alimenta ninguna cifra del dashboard: solo la
    # fecha del pie. Ver el comentario de `pintarStats`. Se sigue inyectando
    # como ESTADS para no romper la plantilla, pero si aparece una cifra nueva
    # ahi, esta mal: se cuenta sobre DATOS.
    estads = cargar_json("estadisticas.json", {})
    if not vacantes:
        log("No hay vacantes.json — ejecuta pipeline.py primero")
        return SALIDA

    # Se recorta la descripción para que el HTML no se dispare de tamaño.
    ligeras = []
    for v in vacantes:
        w = dict(v)
        w["descripcion"] = (w.get("descripcion") or "")[:1500]
        w.pop("extra", None)
        ligeras.append(w)

    # La configuracion activa se resuelve ANTES de meter los datos: asi ningun
    # texto de una vacante puede confundirse con un marcador de la plantilla.
    # Los textos de zona van sin escapar porque salen de `areas.ZONAS`, que es
    # codigo; el nombre sale de perfil.py y se escapa.
    ctx = areas.contexto_panel()
    zona = ctx["zona"]
    etiquetas_areas = ("todas las áreas" if ctx["todas"]
                       else " · ".join(a["etiqueta"] for a in ctx["areas"]))
    valores = sorted(areas.valores_activos(), key=lambda x: (-areas.peso(x), x))
    rx_zona = (f"new RegExp({json.dumps(zona['regex'], ensure_ascii=False)}, 'i')"
               if zona["regex"] else "null")
    html = (
        PLANTILLA
        .replace("__NOMBRE__", escape(str(CANDIDATO.get("nombre") or "")))
        .replace("__AREAS__", escape(etiquetas_areas))
        .replace("__SUB_ZONA__", escape(f"{zona['corta']} presencial + remoto"
                                        if zona["regex"] else "todo México + remoto"))
        .replace("__ETIQ_AREA__", json.dumps(ctx["etiquetas_area"], ensure_ascii=False))
        .replace("__VALORES_AREA__", json.dumps(valores, ensure_ascii=False))
        .replace("__RX_ZONA__", rx_zona)
        .replace("__ETIQ_ZONA__", f"En {zona['corta']}" if zona["regex"] else "Sin zona base")
        .replace("__ZONA_CORTA__", zona["corta"])
        # Solo viaja la fecha. Antes se volcaba `estadisticas.json` entero y
        # el HTML se quedaba con `"vivas": 2228` incrustado: aunque ya no se
        # pinte, un JSON con una cifra falsa dentro del entregable es una
        # trampa esperando a que alguien la lea.
        .replace("__ESTADS__", json.dumps(
            {"generado": estads.get("generado", "")}, ensure_ascii=False))
        .replace("__FECHA__", estads.get("generado", "")[:16].replace("T", " "))
        .replace("__DATOS__", json.dumps(ligeras, ensure_ascii=False))
    )
    SALIDA.write_text(html, encoding="utf-8")
    log(f"Dashboard generado: {SALIDA}  ({len(html)//1024} KB, {len(ligeras)} vacantes)")
    return SALIDA


if __name__ == "__main__":
    generar()
