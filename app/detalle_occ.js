// Lee la FICHA de cada vacante de OCC y saca los campos que deciden si
// se puede postular. Se ejecuta en una pestaña ya abierta en
// occ.com.mx: las peticiones van del mismo origen, con sus cookies, y por eso
// el sitio no responde 403 como haría ante un GET desde Python.
//
// Vive en un archivo .js aparte y no dentro de una cadena de Python a
// propósito: metido en un heredoc, los `\n` de las expresiones regulares se
// convertían en saltos de línea reales y la plantilla quedaba rota. Aquí el
// texto es el texto.
//
// Los ids se inyectan sustituyendo __IDS__.
const ids = __IDS__;
const out = [];

// El HTML que sirve OCC es el armazón de su SPA, pero los campos etiquetados
// aparecen en el texto y la ubicación REAL está en el JSON-LD.
const texto = (h) => {
  const r = h.replace(/<script[\s\S]*?<\/script>/gi, ' ')
             .replace(/<style[\s\S]*?<\/style>/gi, ' ')
             .replace(/<\/(p|div|li|h[1-6]|tr|section)>/gi, '\n')
             .replace(/<br\s*\/?>/gi, '\n')
             .replace(/<[^>]+>/g, ' ');
  const d = new DOMParser().parseFromString('<body>' + r + '</body>', 'text/html');
  return (d.body.textContent || '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n');
};

const campo = (t, etiqueta) => {
  const m = t.match(new RegExp(etiqueta + '\\s*:?\\s*\\n?\\s*([^\\n]{2,40})', 'i'));
  return m ? m[1].trim() : '';
};

// OCC cierra su bloque JSON-LD con "};", que es JSON inválido: hay que
// recortar del primer { al último }. Y usa las claves en Mayúscula ("Url",
// "Title", "JobLocation"), fuera del estándar de schema.org, así que se leen
// las dos grafías.
const ld = (h) => {
  const s = new DOMParser().parseFromString(h, 'text/html')
              .querySelector('script[type="application/ld+json"]');
  if (!s) return null;
  const b = s.textContent, a = b.indexOf('{'), z = b.lastIndexOf('}');
  try { return JSON.parse(b.slice(a, z + 1)); } catch (e) { return null; }
};

// SEGUNDA VIA PARA LA UBICACION, y por que hace falta (28-ago-2026).
//
// El lector de arriba saca la ciudad del JSON-LD, y eso funciona en la mayoria
// de las fichas. Pero hay fichas VIVAS que no lo traen: ese dia quedaron dos
// que devolvian 200 y 128 KB sin un solo bloque `application/ld+json`, asi que
// se quedaban con `ubicacion_ficha` vacia y la base seguia diciendo "Nuevo
// Leon, Mexico" -- que es justo el dato que este trabajo existe para corregir.
// Una de ellas era "especialista en riesgo operacional TI presencial LEON
// GUANAJUATO": la ciudad estaba a la vista en el titulo de la pagina.
//
// OCC escribe en `og:title` y en `og:description` el puesto y el estado. Se
// lee de ahi, pero **solo si aparece un estado mexicano reconocible**: escribir
// un texto cualquiera en `ubicacion_ficha` seria peor que dejarlo vacio,
// porque de esa columna dependen los filtros que deciden si se puede
// postular sin mudarse. Vacio significa "no se sabe"; un valor inventado
// significa "se sabe, y es mentira".
const ESTADOS = ['aguascalientes','baja california sur','baja california','campeche',
 'chiapas','chihuahua','coahuila','colima','durango','guanajuato','guerrero','hidalgo',
 'jalisco','estado de mexico','michoacan','morelos','nayarit','nuevo leon','oaxaca',
 'puebla','queretaro','quintana roo','san luis potosi','sinaloa','sonora','tabasco',
 'tamaulipas','tlaxcala','veracruz','yucatan','zacatecas','ciudad de mexico','cdmx'];

const sinAcentos = (t) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

const ubicacionDeMeta = (h) => {
  const d = new DOMParser().parseFromString(h, 'text/html');
  const partes = [
    (d.querySelector('meta[property="og:title"]') || {}).content || '',
    (d.querySelector('meta[property="og:description"]') || {}).content || '',
    d.title || ''
  ].join(' | ');
  const plano = sinAcentos(partes);
  // El estado mas largo que aparezca: "baja california sur" antes que
  // "baja california", "nuevo leon" antes que "leon" (que ni siquiera es un
  // estado, es una ciudad de Guanajuato -- y confundirlas es exactamente el
  // error que se quiere evitar).
  for (const e of ESTADOS) {
    if (plano.includes(e)) return e.replace(/(^|\s)\S/g, (c) => c.toUpperCase());
  }
  return '';
};

const uno = async (id) => {
  try {
    const r = await fetch('/empleo/oferta/' + id + '/', {credentials: 'include', redirect: 'follow'});
    const crudo = await r.text();
    const t = texto(crudo);
    const bajo = t.toLowerCase();

    // Solo el 404/410 del portal cierra una vacante. Un 403 o un 429
    // significan "no me dejan mirar", nunca "ya no existe".
    let estado = (r.status === 404 || r.status === 410) ? 'cerrada'
               : /no podemos encontrar la vacante/.test(bajo) ? 'cerrada'
               : /postularme|ya est[aá]s postulado/.test(bajo) ? 'viva'
               : 'sin-verificar';

    const j = ld(crudo) || {};
    const dir = (j.JobLocation && j.JobLocation.Address)
             || (j.jobLocation && j.jobLocation.address) || {};
    const ciudad = dir.AddressLocality || dir.addressLocality || '';
    const region = dir.AddressRegion || dir.addressRegion || '';

    // El JSON-LD manda; las metaetiquetas son el plan B.
    const deLD = [ciudad, region].filter(Boolean).join(', ');

    out.push([
      id,
      estado,
      campo(t, 'Educaci[oó]n m[ií]nima requerida'),
      campo(t, 'Contrataci[oó]n'),
      campo(t, 'Horario'),
      campo(t, 'Espacio de trabajo'),
      deLD || ubicacionDeMeta(crudo)
    ].join('|'));
  } catch (x) {
    out.push(id + '|inaccesible|||||');
  }
};

// De seis en seis: en bloques mayores OCC empieza a tardar y a cortar.
for (let i = 0; i < ids.length; i += 6) {
  await Promise.all(ids.slice(i, i + 6).map(uno));
}

// Se manda al panel local, que lo escribe en la base.
//
// `no-cors` y `text/plain` a propósito, y por dos motivos distintos:
//   - text/plain evita la petición previa OPTIONS, que el servidor no atiende.
//   - no-cors significa que la respuesta NO se puede leer desde aquí, y eso es
//     justo lo que se quiere: el buzón queda de solo escritura, así que
//     ninguna web que visites puede leer tus vacantes desde él.
// La confirmación se saca consultando la base, que es la fuente de verdad.
let enviadas = 0;
for (let i = 0; i < out.length; i += 50) {
  try {
    await fetch('http://127.0.0.1:8800/api/detalle', {
      method: 'POST',
      mode: 'no-cors',
      headers: {'Content-Type': 'text/plain'},
      body: JSON.stringify({filas: out.slice(i, i + 50)})
    });
    enviadas += out.slice(i, i + 50).length;
  } catch (e) { /* el panel no esta levantado: quedan en `out` */ }
}

'procesadas ' + out.length + ', enviadas al panel ' + enviadas
