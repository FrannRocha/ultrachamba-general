"""
Catalogo de formacion gratuita, con cada URL comprobada con una peticion real.

Este archivo es la fuente escrita a mano; `cursos.py` la puntua y la verifica.
Se escribe a mano a proposito: los cursos no tienen APIs ni bolsas que
rastrear, y una lista corta y comprobada vale mas que un rastreador que
devuelve ruido.

Como se lleno. Un agente verifico las 26 entradas una por una con peticiones
reales el 18-20 de agosto de 2026, distinguiendo lo gratis de verdad de lo que
solo lo parece. Lo que no se pudo confirmar quedo fuera o marcado.

Descartados con evidencia, para que nadie los vuelva a proponer:
  - SANS Cyber Aces: RETIRADO por la propia SANS el 1 de junio de 2023.
  - Mexico X: caido, 522 de Cloudflare tambien en navegador real.
  - Jovenes Construyendo el Futuro: exige NO estar estudiando.
  - "Talento Tierra": no existe con ese nombre.
  - Microsoft Virtual Training Days: ya NO regala el examen, solo 50% de
    descuento. Cualquier guia que diga "AZ-900 gratis con MVTD" esta vieja.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# El hallazgo que reordena la lista: ORACLE regala curso Y examen.
#
# Comparado el 18-ago-2026:
#     AWS Cloud Practitioner ...... 100 USD el examen
#     Microsoft AZ-900 ............  99 USD el examen
#     Cisco CCST Cybersecurity .... 125 USD el examen
#     Oracle OCI Foundations ......   0 USD, curso y examen
#
# Para alguien que no puede pagar, esa diferencia decide. Y desde el 10 de
# agosto de 2026 Oracle amplio la gratuidad al nivel Associate, que en un CV
# junior pesa mucho mas que un curso de introduccion.
# ---------------------------------------------------------------------------

CATALOGO = [
    {
        "nombre": "OCI Foundations Associate",
        "institucion": "Oracle University",
        "url": "https://mylearn.oracle.com/ou/learning-path/become-an-oci-foundations-associate-2026/",
        "area": "nube", "modalidad": "linea", "gratis": "total",
        "credencial": "Oracle Cloud Infrastructure Foundations Associate (vigencia 24 meses)",
        "convocatoria": "permanente", "duracion": "10-15 horas", "idioma": "ingles",
        "descripcion": "Ruta oficial de Oracle sobre nube: computo, almacenamiento, "
                       "redes e identidad. Curso y examen de certificacion sin costo.",
        "por_que": "Unica certificacion de nube de fabricante con examen gratis: "
                   "ataca de frente el 21,6% de vacantes que piden nube.",
    },
    {
        "nombre": "OCI Architect Associate",
        "institucion": "Oracle University",
        "url": "https://mylearn.oracle.com/ou/learning-path/become-an-oci-architect-associate-2026/",
        "area": "nube", "modalidad": "linea", "gratis": "total",
        "credencial": "Oracle Cloud Infrastructure Architect Associate",
        "convocatoria": "permanente", "duracion": "30-40 horas", "idioma": "ingles",
        "descripcion": "Nivel associate de Oracle Cloud: identidad, redes, computo y "
                       "almacenamiento. Gratis desde el 10 de agosto de 2026.",
        "por_que": "Un associate pesa mucho mas en un CV junior que un curso de "
                   "introduccion, y sigue costando cero.",
    },
    {
        "nombre": "Samsung Innovation Campus 2026 — sede Nuevo Leon",
        "institucion": "Samsung + UDEM",
        "url": "https://samsunginnovationcampus.udem.edu.mx/",
        "area": "ia", "modalidad": "presencial-mty", "gratis": "beca",
        "credencial": "Constancia UDEM, contenido avalado por CENEVAL",
        "convocatoria": "abierta", "cierra": "2026-09-18",
        "duracion": "168 horas en 14 semanas (5 oct 2026 - 23 ene 2027)",
        "idioma": "espanol",
        "descripcion": "Programa de inteligencia artificial con 60 horas en linea y 8 "
                       "sesiones presenciales en Nuevo Leon, de 17:00 a 20:00. Examen de "
                       "seleccion del 25 de agosto al 22 de septiembre y entrevista.",
        "por_que": "Presencial en Monterrey, marca fuerte y red local. OJO: las bases "
                   "exigen estudiar en INSTITUCION PUBLICA; verificar antes de invertir "
                   "tiempo en la postulacion.",
    },
    {
        "nombre": "Junior Cybersecurity Analyst Career Path",
        "institucion": "Cisco Networking Academy",
        "url": "https://www.netacad.com/career-paths/cybersecurity",
        "area": "ciberseguridad", "modalidad": "linea", "gratis": "examen-pago",
        "costo_examen": "unos 125 USD el CCST, opcional",
        "credencial": "Insignia digital de Cisco al terminar la ruta",
        "convocatoria": "permanente", "duracion": "120 horas", "idioma": "espanol",
        "descripcion": "Seis cursos en espanol que forman el perfil de analista de "
                       "seguridad de primer nivel. El material es gratis; el examen CCST "
                       "es opcional y de pago.",
        "por_que": "Es exactamente el perfil Tier 1 que piden las practicas de "
                   "ciberseguridad, y la insignia de la ruta no cuesta nada.",
    },
    {
        "nombre": "AWS Educate",
        "institucion": "Amazon Web Services",
        "url": "https://aws.amazon.com/education/awseducate/",
        "area": "nube", "modalidad": "linea", "gratis": "total",
        "credencial": "Insignias digitales compartibles de AWS",
        "convocatoria": "permanente", "duracion": "a tu ritmo", "idioma": "ingles",
        "descripcion": "Laboratorios reales de S3, EC2 y VPC sin tarjeta de credito, "
                       "con insignias digitales. Incluye bolsa de empleo y practicas "
                       "para mayores de 18.",
        "por_que": "Practica de nube sin pagar nada y con bolsa de practicas propia.",
    },
    {
        "nombre": "Fortinet Certified Fundamentals (FCF)",
        "institucion": "Fortinet Training Institute",
        "url": "https://training.fortinet.com/",
        "area": "ciberseguridad", "modalidad": "linea", "gratis": "total",
        "credencial": "Certificacion Fortinet Certified Fundamentals",
        "convocatoria": "permanente", "duracion": "8-10 horas", "idioma": "ingles",
        "descripcion": "Certificacion de fundamentos de un fabricante de seguridad, "
                       "sin examen de pago: se obtiene al completar los cursos.",
        "por_que": "Certificacion de fabricante a coste cero que se saca en un fin de "
                   "semana. Relacion esfuerzo-credencial imbatible.",
    },
    {
        "nombre": "Hola IA: Mundial Inteligente",
        "institucion": "CSOFTMTY + IBM SkillsBuild + Gobierno de Nuevo Leon",
        "url": "https://csoftmty.org/hola-ia-mundial-inteligente/",
        "area": "ia", "modalidad": "linea", "gratis": "total",
        "credencial": "IBM SkillsBuild (el FAQ del sitio esta roto y no se pudo confirmar)",
        "convocatoria": "abierta", "duracion": "20 minutos + 4 horas + 10 horas",
        "idioma": "espanol",
        "descripcion": "Programa de IA del cluster de tecnologia de Nuevo Leon con IBM "
                       "SkillsBuild y el gobierno del estado.",
        "por_que": "CSOFTMTY agrupa a las empresas de TI que contratan en Monterrey: "
                   "el valor real es la puerta local, no el contenido.",
    },
    {
        "nombre": "IBM SkillsBuild",
        "institucion": "IBM",
        "url": "https://skillsbuild.org/es",
        "area": "ia", "modalidad": "linea", "gratis": "total",
        "credencial": "Credenciales digitales de IBM",
        "convocatoria": "permanente", "duracion": "variable", "idioma": "espanol",
        "descripcion": "Catalogo gratuito en espanol de IA, ciberseguridad y datos, con "
                       "insignias digitales de IBM. No hace falta universidad aliada.",
        "por_que": "Credenciales de una marca conocida, en espanol y sin coste.",
    },
    {
        "nombre": "Escuela Publica de Codigo / CPF-IA",
        "institucion": "INFOTEC - ATDT (gobierno federal), plataforma Saberes",
        "url": "https://saberes.gob.mx/cms/index.php/cfia",
        "area": "ia", "modalidad": "linea", "gratis": "total",
        "credencial": "Constancia (el propio sitio avisa de que NO es certificacion profesional)",
        "convocatoria": "abierta", "duracion": "30 horas, 4 modulos por curso",
        "idioma": "espanol",
        "descripcion": "Cursos de IA y programacion del gobierno federal con "
                       "autoinscripcion abierta ahora mismo.",
        "por_que": "Era lo unico del gobierno federal con autoinscripcion abierta al "
                   "revisar el catalogo, mientras se espera la proxima convocatoria "
                   "de MEXIA.",
    },
    {
        "nombre": "Azure for Students",
        "institucion": "Microsoft",
        "url": "https://azure.microsoft.com/es-mx/free/students/",
        "area": "nube", "modalidad": "linea", "gratis": "total",
        "credencial": "",
        "convocatoria": "permanente", "duracion": "12 meses renovables",
        "idioma": "espanol",
        "descripcion": "Cien dolares de credito en Azure sin tarjeta de credito, "
                       "renovable cada ano mientras sea estudiante.",
        "por_que": "Practicar en Azure de verdad sin riesgo de cobros, y lo que se "
                   "construya llena la seccion de proyectos del CV.",
    },
    {
        "nombre": "MEXIA / CPFIA — vigilar la proxima convocatoria",
        "institucion": "ATDT-INFOTEC, SEP, SECIHTI, IPN, TecNM, AMITI",
        "url": "https://www.mexia.gob.mx/convocatoria/",
        "area": "nube", "modalidad": "linea", "gratis": "total",
        "credencial": "Google Cloud Engineer, Cisco Cybersecurity Essentials, OCI AI Foundations",
        "convocatoria": "cerrada", "cierra": "2026-07-05",
        "duracion": "5 meses, con ingles en paralelo", "idioma": "espanol",
        "descripcion": "El programa federal mas completo: certificaciones de fabricante "
                       "gratuitas con miles de lugares. Registro del 26 de mayo al 5 de "
                       "julio de 2026. La web anuncia mas convocatorias proximamente.",
        "por_que": "Es el mejor programa de toda la lista y se cerro hace seis semanas. "
                   "Hay que vigilar la tercera convocatoria cada semana.",
    },
    {
        "nombre": "Kaggle Learn",
        "institucion": "Kaggle (Google)",
        "url": "https://www.kaggle.com/learn",
        "area": "ia", "modalidad": "linea", "gratis": "total",
        "credencial": "Certificados de finalizacion gratuitos",
        "convocatoria": "permanente", "duracion": "3-7 horas por curso",
        "idioma": "ingles",
        "descripcion": "Cursos cortos y practicos de datos y aprendizaje automatico, "
                       "con cuadernos publicos.",
        "por_que": "Certificados gratis y, sobre todo, cuadernos publicos que funcionan "
                   "como portafolio demostrable.",
    },
    {
        "nombre": "Agents Course",
        "institucion": "Hugging Face",
        "url": "https://huggingface.co/learn/agents-course",
        "area": "ia", "modalidad": "linea", "gratis": "total",
        "credencial": "Certificado del curso",
        "convocatoria": "permanente", "duracion": "unas 20 horas", "idioma": "ingles",
        "descripcion": "Curso practico sobre agentes de IA, con certificado gratuito.",
        "por_que": "Los agentes de IA son lo que mas se pide ahora, y encaja con "
                   "perfiles que combinan IA y seguridad.",
    },
    {
        "nombre": "Microsoft Learn — AZ-900 y SC-900",
        "institucion": "Microsoft",
        "url": "https://learn.microsoft.com/es-mx/credentials/certifications/azure-fundamentals/",
        "area": "nube", "modalidad": "linea", "gratis": "examen-pago",
        "costo_examen": "unos 99 USD",
        "credencial": "Microsoft Certified: Azure Fundamentals (solo pagando el examen)",
        "convocatoria": "permanente", "duracion": "10-20 horas", "idioma": "espanol",
        "descripcion": "Temario oficial en espanol de fundamentos de Azure y de "
                       "seguridad. El material es gratis; el examen no.",
        "por_que": "Buen temario en espanol, pero la credencial cuesta dinero "
                   "mientras Oracle regale la suya.",
    },
    {
        "nombre": "Google Cloud Skills Boost",
        "institucion": "Google Cloud",
        "url": "https://www.skills.google/",
        "area": "nube", "modalidad": "linea", "gratis": "examen-pago",
        "costo_examen": "los laboratorios con insignia exigen creditos",
        "credencial": "Insignias de finalizacion (gratis) e insignias de habilidad (con creditos)",
        "convocatoria": "permanente", "duracion": "30+ horas la ruta de fundamentos",
        "idioma": "espanol",
        "descripcion": "Cursos e insignias de finalizacion gratuitos; los laboratorios "
                       "practicos requieren creditos. Los estudiantes pueden pedirlos.",
        "por_que": "Tercera nube del CV. Sin creditos se queda a medias, asi que va "
                   "detras de Oracle y AWS Educate.",
    },
    {
        "nombre": "AWS Skill Builder — Cloud Practitioner",
        "institucion": "Amazon Web Services",
        "url": "https://skillbuilder.aws/",
        "area": "nube", "modalidad": "linea", "gratis": "examen-pago",
        "costo_examen": "100 USD",
        "credencial": "AWS Certified Cloud Practitioner (solo pagando)",
        "convocatoria": "permanente", "duracion": "unas 20 horas", "idioma": "espanol",
        "descripcion": "Preparacion oficial para la certificacion de fundamentos de AWS.",
        "por_que": "Prepararlo gratis tiene sentido; presentarlo no, mientras Oracle "
                   "regale el suyo.",
    },
    {
        "nombre": "TryHackMe — plan gratuito",
        "institucion": "TryHackMe",
        "url": "https://tryhackme.com/",
        "area": "ciberseguridad", "modalidad": "linea", "gratis": "examen-pago",
        "costo_examen": "el certificado de ruta exige suscripcion, unos 10,50 EUR al mes",
        "credencial": "",
        "convocatoria": "permanente", "duracion": "a tu ritmo", "idioma": "ingles",
        "descripcion": "Salas gratuitas de practica ofensiva, con una hora diaria de "
                       "maquina de ataque. El certificado de ruta es solo de pago.",
        "por_que": "Practica real que se nota en la entrevista tecnica, pero NO deja "
                   "papel: sirve para defenderse hablando, no para el CV.",
    },
    {
        "nombre": "Elements of AI",
        "institucion": "Universidad de Helsinki + MinnaLearn",
        "url": "https://www.elementsofai.com/",
        "area": "ia", "modalidad": "linea", "gratis": "total",
        "credencial": "Certificado gratuito",
        "convocatoria": "permanente", "duracion": "unas 30 horas", "idioma": "espanol",
        "descripcion": "Introduccion solida a la inteligencia artificial, en espanol, "
                       "con certificado sin coste.",
        "por_que": "Buena entrada en espanol con certificado gratis, aunque su peso de "
                   "marca es moderado.",
    },
    {
        "nombre": "OWASP Juice Shop",
        "institucion": "OWASP Foundation",
        "url": "https://owasp.org/www-project-juice-shop/",
        "area": "ciberseguridad", "modalidad": "linea", "gratis": "total",
        "credencial": "",
        "convocatoria": "permanente", "duracion": "a tu ritmo", "idioma": "ingles",
        "descripcion": "Aplicacion deliberadamente vulnerable para practicar seguridad "
                       "de aplicaciones en local.",
        "por_que": "Material para escribir reportes tecnicos propios y demostrar "
                   "practica real, que es lo que mira un reclutador tecnico.",
    },
    {
        "nombre": "Capacitate para el Empleo",
        "institucion": "Fundacion Carlos Slim",
        "url": "https://capacitatecarso.com/",
        "area": "general", "modalidad": "linea", "gratis": "total",
        "credencial": "Certificado por curso",
        "convocatoria": "permanente", "duracion": "variable", "idioma": "espanol",
        "descripcion": "Catalogo gratuito con certificado, de nivel basico en tecnologia.",
        "por_que": "Certificados gratis, pero contenido basico: sirve de relleno, no "
                   "de diferenciador.",
    },
]
