// Lee las fichas de Indeed y saca estado, tipo de contrato y ubicación real.
// Se ejecuta en una pestaña abierta en mx.indeed.com.
//
// LO QUE COSTÓ ENCONTRAR, y por qué está escrito aquí:
//
// 1. La ficha pedida por `fetch` llega completa (~300 KB) pero **sin el
//    JSON-LD**: ese bloque lo inyecta el JavaScript al renderizar. Buscarlo
//    ahí devuelve vacío siempre.
//
// 2. La frase "Este empleo caducó en Indeed" aparece en el HTML de TODAS las
//    vacantes, caducadas y vivas: forma parte de una plantilla incrustada.
//    Detectar la caducidad por texto marca como muertas vacantes vivas. Se
//    probó y falló contra Getsemani (caducada) y Janus (viva): las dos daban
//    positivo.
//
// 3. Lo que sí distingue es la bandera `isJobExpired`. Se encontró
//    comparando el conjunto de claves booleanas en `true` de una ficha
//    caducada contra una viva: solo `isJobExpired` y `showExpiredHeader`
//    aparecían en la caducada. Validado contra cinco vacantes de estado
//    conocido de primera mano: cinco aciertos.
//
// Los ids (jk) se inyectan sustituyendo __IDS__.
const ids = __IDS__;
const out = [];

const uno = async (jk) => {
  try {
    const r = await fetch('/viewjob?jk=' + jk, {credentials: 'include'});
    const h = await r.text();

    // GUARDA CONTRA EL ESTRANGULAMIENTO. Tras ~120 peticiones seguidas,
    // Indeed deja de servir la ficha real (~300 KB) y devuelve una version
    // recortada de ~28 KB, con status 200 y sin ninguna de las claves.
    //
    // Es el peor escenario posible: sin esta comprobacion, TODAS salen
    // "viva" y sin datos, y una vacante caducada quedaria marcada como viva
    // en la base. Se detecto porque Getsemani --caducada -- empezo a dar
    // "viva" a mitad de una tanda.
    //
    // Ante la duda se devuelve 'inaccesible', que no escribe nada. Preferimos
    // no saber a saber mal.
    if (!/"formattedLocation"/.test(h)) {
      out.push(jk + '|inaccesible|||||');
      return;
    }

    const sacar = (clave) => {
      const m = h.match(new RegExp('"' + clave + '"\\s*:\\s*"([^"]{0,40})"'));
      return m ? m[1].replace(/\|/g, ' ') : '';
    };

    // La bandera, no la frase. Ver el punto 2 de arriba.
    const caducada = /"isJobExpired"\s*:\s*true/.test(h);

    const lugar = sacar('formattedLocation');
    const tipo = sacar('jobType');

    // Indeed pone "Desde casa" en la propia ubicación cuando es remota, así
    // que el espacio de trabajo se deduce de ahí sin campo aparte.
    const espacio = /desde casa|remoto/i.test(lugar) ? 'Desde Casa'
                  : /h[ií]brido/i.test(lugar) ? 'Hibrido' : '';

    out.push([jk, caducada ? 'cerrada' : 'viva', '', tipo, '', espacio, lugar].join('|'));
  } catch (e) {
    out.push(jk + '|inaccesible|||||');
  }
};

// De DOS en dos y con pausa. Medido el 24-ago-2026: a ritmo de cuatro en
// paralelo sin pausa, Indeed corta a las ~120 peticiones y ya no se recupera
// en la misma sesion. Ir despacio no es prudencia abstracta: es la diferencia
// entre enriquecer las 231 en varias tandas o quemar el acceso en una.
//
// Si empiezan a salir 'inaccesible' seguidas, se para: significa que ya
// cortaron y todo lo que venga detras seria ruido.
let seguidas = 0;
for (let i = 0; i < ids.length; i += 2) {
  await Promise.all(ids.slice(i, i + 2).map(uno));
  const ultimas = out.slice(-2);
  seguidas = ultimas.every(x => x.includes('|inaccesible|')) ? seguidas + 1 : 0;
  if (seguidas >= 3) { out.push('__CORTADO__|parado tras ' + out.length + ' fichas'); break; }
  await new Promise(r => setTimeout(r, 900));
}

// OJO CON EL TRANSPORTE. Desde una pestaña de OCC, el POST a
// http://127.0.0.1:8800 funciona. **Desde Indeed no**, y no es cosa de
// cabeceras: se probó `no-cors`, `sendBeacon` (devuelve true y no entrega
// nada) y CORS completo con `Access-Control-Allow-Private-Network`. Chrome
// bloquea igual la conexión de esta página HTTPS hacia la red privada.
//
// Así que aquí las filas se DEVUELVEN, y quien llame las vuelca con
// `verificador_chrome.guardar_detalle`. Menos elegante, pero funciona.
out.join('\n')
