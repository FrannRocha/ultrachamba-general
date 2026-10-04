"""
Personas a quien escribir, con su grado de certeza.

De donde deben salir. SOLO de fuentes profesionales publicas: perfiles
corporativos oficiales, documentos de equipo directivo, fichas de ponentes de
congresos y notas de prensa. Nada de herramientas de OSINT de brechas ni de
corredores de datos (RocketReach, ContactOut, ZoomInfo, LeadIQ, D&B): revenden
informacion personal, no son fuentes. En Mexico, tratar datos personales sin
base legal choca ademas con la LFPDPPP.

EL AVISO MAS IMPORTANTE DE ESTE ARCHIVO
---------------------------------------
**Un correo deducido por patron NO esta verificado.** Aplicar el patron de la
empresa al nombre de una persona puede rebotar. El campo `correo_origen` lo
dice en cada fila y el panel tiene que ensenarlo: presentar un correo deducido
como confirmado hace que se escriba a una direccion inexistente creyendo que se
acerto, esperando una respuesta que nunca llega.

Lo que si se puede verificar es el DOMINIO, cuando la propia empresa publico
algun correo de ese dominio en un documento oficial.

A QUIEN ESCRIBIR
----------------
Los reclutadores rara vez aparecen en fuentes publicas; los responsables del
area si (ponencias, biografias, entrevistas). A un buzon sin cara no se le
puede escribir algo que solo le sirva a el; a alguien cuya charla viste, si.

Con un limite: **donde hay programa formal de becarios con fechas, escribirle
al responsable NO salta la fila y puede molestar.** Ahi se postula por el
portal y el correo directo es, como mucho, un refuerzo.

LOS VALORES DE ABAJO SON EJEMPLOS FICTICIOS e inertes: sus empresas no existen
en la tabla `empresas`, asi que `cargar_contactos.py` los deja sin enlazar, y
la cola solo usa contactos enlazados y verificados. El dominio `example.com`
esta reservado (RFC 2606): ningun correo puede llegar a una persona.
"""
from __future__ import annotations

# Cada entrada lleva `empresa` tal como aparece en la tabla `empresas`, para
# poder enlazarla. Si el nombre no coincide, la fila se queda sin enlazar y se
# reporta en vez de inventar la union.
CONTACTOS = [
    {
        "empresa": "EJEMPLO — Otra Empresa Ficticia",
        "nombre": "EJEMPLO — Nombre Apellido",
        "puesto": "EJEMPLO — Responsable del area",
        "correo": "nombre.apellido@example.com",
        "correo_origen": "inferido-por-patron", "confianza": "inferido",
        "fuente": "EJEMPLO — pagina oficial de equipo directivo (URL y fecha)",
        "notas": "EJEMPLO FICTICIO: por que esta persona y no otra, y si la "
                 "empresa tiene programa formal de becarios.",
    },
]

# Puertas institucionales con correo PUBLICADO (camaras, clusteres,
# asociaciones): presentan a muchas empresas a la vez.
PUERTAS = [
    {
        "empresa": "EJEMPLO — Asociacion Ficticia A.C.",
        "nombre": "EJEMPLO — Contacto institucional",
        "puesto": "EJEMPLO — Buzon general",
        "correo": "contacto@example.com", "correo_origen": "publicado",
        "confianza": "inferido",
        "fuente": "EJEMPLO — sitio oficial (URL)",
        "notas": "EJEMPLO FICTICIO: que presenta y a quien.",
    },
]
