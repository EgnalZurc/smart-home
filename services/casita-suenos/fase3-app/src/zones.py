"""
Configuracion de las 13 zonas candidatas del estudio (Fase 1).
Las URLs de busqueda se rellenan con patrones reales de cada portal.
"""
from models import FireRisk, FloodRisk, Zone
# ---------------------------------------------------------------------------
# Las 13 zonas con mayor puntuacion del estudio peninsular
# P11: gusto personal por la provincia (0-9)
# P12: riesgo inundacion segun SNCZI/CHE/CHC/PATRICOVA (0-9, ALTO = L12 descarte)
# ---------------------------------------------------------------------------

# Coordenadas de referencia (lat, lon) del centroide de cada zona
# Usadas para el fallback geográfico cuando no hay match por keywords
ZONE_COORDS: dict[str, tuple[float, float]] = {
    "zamora_meseta":          (41.503, -5.744),   # Zamora ciudad
    "castellon_costa_norte":  (40.476,  0.475),   # Vinaròs–Benicarló
    "salamanca_alrededores":  (40.965, -5.664),   # Salamanca capital
    "la_rioja_valle":         (42.430, -2.428),   # Alberite / Logroño
    "valencia_costa_norte":   (39.681, -0.271),   # Sagunto
    "palencia_alrededores":   (41.997, -4.530),   # Palencia / Venta de Baños
    "navarra_ribera":         (42.063, -1.608),   # Tudela
    "burgos_sur":             (41.671, -3.690),   # Aranda de Duero
    "valladolid_rural":       (41.652, -4.724),   # Valladolid meseta
    "cuenca_alrededores":     (40.070, -2.138),   # Cuenca capital
    "burgos_norte_merindad":  (42.931, -3.484),   # Medina de Pomar
    "cantabria_liebana":      (43.154, -4.620),   # Potes
    "asturias_oriente":       (43.484, -5.435),   # Villaviciosa–Ribadesella
}
ZONES: dict[str, Zone] = {
    z.id: z for z in [
        Zone(
            id="zamora_meseta",
            name="Zamora meseta central (Arcenillas, Villaralbo, Morales del Vino)",
            distance_madrid_min=150,
            distance_beach_min=None,
            distance_natural_pools_min=30,
            distance_supermarket_min=10,
            distance_health_center_min=8,
            distance_hospital_min=12,
            fire_risk=FireRisk.NULO,
            zone_preference=5.0,
            flood_risk=FloodRisk.BAJO_MEDIO,  # valle Duero, SNCZI T=100/500 floodplain
            price_min=59_000,
            price_max=259_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-zamora.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-zamora/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("zamora", "arcenillas", "villaralbo", "morales del vino"),
            fotocasa_municipios=("zamora", "arcenillas", "villaralbo", "morales-del-vino", "el-perdigon", "fresno-de-la-ribera", "molacillos", "santa-clara-de-avedillo"),
        ),
        Zone(
            id="castellon_costa_norte",
            name="Castellon costa norte (Vinaros, Benicarlo, Peniscola)",
            distance_madrid_min=225,
            distance_beach_min=5,
            distance_natural_pools_min=30,
            distance_supermarket_min=5,
            distance_health_center_min=5,
            distance_hospital_min=8,
            fire_risk=FireRisk.MUY_BAJO,
            zone_preference=6.0,
            flood_risk=FloodRisk.MEDIO,  # barrancos costeros, DANA, boca Cervol
            price_min=250_000,
            price_max=450_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-vinaros.htm",
                "https://www.habitaclia.com/casas-benicarlo.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-vinaros/habitaciones-3/jardin/",
                "https://www.pisos.com/venta/casas-benicarlo/habitaciones-3/jardin/",
            ),
                        has_coast=True,
            idealista_alert_keywords=("vinaros", "benicarlo", "peniscola"),
            fotocasa_municipios=("vinaros", "benicarlo", "peniscola", "santa-barbara", "amposta", "deltebre", "tortosa", "alcanar", "ulldecona", "la-senia", "gratallops", "vila-real", "benicarló", "peníscola"),
        ),
        Zone(
            id="salamanca_alrededores",
            name="Salamanca alrededores capital (Doninos, Aldearrubia, Villamayor)",
            distance_madrid_min=120,
            distance_beach_min=None,
            distance_natural_pools_min=45,
            distance_supermarket_min=8,
            distance_health_center_min=8,
            distance_hospital_min=12,
            fire_risk=FireRisk.NULO,
            zone_preference=5.0,
            flood_risk=FloodRisk.BAJO,  # meseta alta, rio Tormes con gradiente suave
            price_min=183_000,
            price_max=299_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-salamanca.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-salamanca/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("doninos", "aldearrubia", "villamayor", "carbajosa"),
            fotocasa_municipios=("carrascal-de-barregas", "doninos-de-salamanca", "aldearrubia", "villamayor-de-la-armunia", "carbajosa-de-la-sagrada", "cabrerizos", "monterrubio-de-la-sierra", "terradillos"),
        ),
        Zone(
            id="la_rioja_valle",
            name="La Rioja valle bajo (Alberite, Navarrete, Fuenmayor)",
            distance_madrid_min=165,
            distance_beach_min=None,
            distance_natural_pools_min=20,
            distance_supermarket_min=8,
            distance_health_center_min=5,
            distance_hospital_min=8,
            fire_risk=FireRisk.NULO,
            zone_preference=7.0,
            flood_risk=FloodRisk.BAJO_MEDIO,  # corredor Ebro-Iregua, inundaciones 2003/2015
            price_min=208_000,
            price_max=300_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-la-rioja.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-villamediana_de_iregua/habitaciones-3/jardin/",
                "https://www.pisos.com/venta/casas-alberite/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("alberite", "navarrete", "fuenmayor", "villamediana"),
            fotocasa_municipios=("alberite", "navarrete", "fuenmayor", "villamediana-de-iregua", "logrono", "lardero", "entrena", "sotillo-cameros", "cenicero", "briones"),
        ),
        Zone(
            id="valencia_costa_norte",
            name="Valencia costa norte (Sagunto, Canet d'En Berenguer, Pucol)",
            distance_madrid_min=210,
            distance_beach_min=5,
            distance_natural_pools_min=15,
            distance_supermarket_min=5,
            distance_health_center_min=5,
            distance_hospital_min=8,
            fire_risk=FireRisk.MUY_BAJO,
            zone_preference=6.0,
            flood_risk=FloodRisk.MEDIO_ALTO,  # DANA corredor Valencia, Palancia, Albufera
            price_min=250_000,
            price_max=400_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-valencia.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-sagunto/habitaciones-3/jardin/",
            ),
                        has_coast=True,
            idealista_alert_keywords=("sagunto", "canet d'en berenguer", "pucol"),
            fotocasa_municipios=("sagunto", "canet-den-berenguer", "pucol", "el-puig-de-santa-maria", "benavites", "faura", "quartell", "benifairo-de-les-valls"),
        ),
        Zone(
            id="palencia_alrededores",
            name="Palencia alrededores (Venta de Banos, Grijota, Reinoso)",
            distance_madrid_min=140,
            distance_beach_min=None,
            distance_natural_pools_min=60,
            distance_supermarket_min=8,
            distance_health_center_min=8,
            distance_hospital_min=18,
            fire_risk=FireRisk.NULO,
            zone_preference=5.0,
            flood_risk=FloodRisk.BAJO_MEDIO,  # confluencia Carrion-Pisuerga, inundaciones 2001/2003
            price_min=159_000,
            price_max=207_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-palencia.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-palencia/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("venta de banos", "grijota", "reinoso", "palencia"),
            fotocasa_municipios=("palencia", "venta-de-banos", "grijota", "reinoso-de-cerrato", "magaz-de-pisuerga", "villamuriel-de-cerrato", "monzon-de-campos", "bustillo-del-paramo", "santa-cristina-de-valmadrigal", "cea", "bercianos-del-real-camino"),
        ),
        Zone(
            id="navarra_ribera",
            name="Navarra Ribera (Tudela, Cadreita, Valtierra)",
            distance_madrid_min=180,
            distance_beach_min=None,
            distance_natural_pools_min=60,
            distance_supermarket_min=5,
            distance_health_center_min=8,
            distance_hospital_min=8,
            fire_risk=FireRisk.BAJO,
            zone_preference=6.0,
            flood_risk=FloodRisk.ALTO,  # L12: Ribera Ebro, zona inundable historica, evacuaciones
            price_min=100_000,
            price_max=200_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-tudela.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-tudela/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("tudela", "cadreita", "valtierra", "ribera navarra"),
            fotocasa_municipios=("tudela", "cadreita", "valtierra", "alfaro", "gallur", "corella", "cintruenigo", "fitero", "cascante", "buñuel"),
        ),
        Zone(
            id="burgos_sur",
            name="Burgos sur (Aranda de Duero, Lerma, Ribera del Duero)",
            distance_madrid_min=140,
            distance_beach_min=None,
            distance_natural_pools_min=60,
            distance_supermarket_min=8,
            distance_health_center_min=8,
            distance_hospital_min=18,
            fire_risk=FireRisk.MUY_BAJO,
            zone_preference=6.0,
            flood_risk=FloodRisk.BAJO,  # Duero encajonado en Aranda, Lerma en alto
            price_min=120_000,
            price_max=220_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-burgos.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-burgos/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("aranda de duero", "lerma", "penaranda de duero"),
            fotocasa_municipios=("fuentespina", "aranda-de-duero", "lerma", "gumiel-de-hizan", "quintanamanvirgo", "vadocondes", "la-aguilera", "penaranda-de-duero", "covarrubias", "moradillo-de-roa"),
        ),
        Zone(
            id="valladolid_rural",
            name="Valladolid rural (municipios meseta, sin pinar)",
            distance_madrid_min=120,
            distance_beach_min=None,
            distance_natural_pools_min=60,
            distance_supermarket_min=12,
            distance_health_center_min=10,
            distance_hospital_min=22,
            fire_risk=FireRisk.NULO,
            zone_preference=4.0,
            flood_risk=FloodRisk.BAJO,  # meseta castellana, buenos drenajes naturales
            price_min=180_000,
            price_max=250_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-valladolid.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-valladolid/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("villaturiel", "santa maria del condado", "mansilla"),
            fotocasa_municipios=("pinarnegrillo", "mojados", "olmedo", "pedrajas-de-san-esteban", "portillo", "aldeatejada", "aldeamayor-de-san-martin", "simancas", "tordesillas"),
        ),
        Zone(
            id="cuenca_alrededores",
            name="Cuenca alrededores capital (Sotos, Arcas, Las Pernalosas)",
            distance_madrid_min=120,
            distance_beach_min=None,
            distance_natural_pools_min=18,
            distance_supermarket_min=12,
            distance_health_center_min=12,
            distance_hospital_min=12,
            fire_risk=FireRisk.MEDIO,
            zone_preference=4.0,
            flood_risk=FloodRisk.BAJO,  # cabecera Jucar, topografia en gorge, drenaje rapido
            price_min=185_000,
            price_max=285_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-cuenca.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-cuenca/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("sotos", "arcas", "pernalosas", "cuenca"),
            fotocasa_municipios=("cuenca", "sotos", "arcas", "las-pernalosas", "mentrida", "fuentes", "gabaldon", "palomera", "el-casar", "guadalajara", "azuqueca-de-henares", "brihuega", "pastrana"),
        ),
        Zone(
            id="burgos_norte_merindad",
            name="Burgos norte / Merindad de Mena (Medina de Pomar, Villarcayo)",
            distance_madrid_min=165,
            distance_beach_min=45,
            distance_natural_pools_min=20,
            distance_supermarket_min=8,
            distance_health_center_min=5,
            distance_hospital_min=55,
            fire_risk=FireRisk.MUY_BAJO,
            zone_preference=6.0,
            flood_risk=FloodRisk.BAJO_MEDIO,  # valles Nela/Trueba, flash floods atlanticos
            price_min=100_000,
            price_max=230_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-burgos.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-burgos/habitaciones-3/jardin/",
            ),
                        has_coast=True,
            idealista_alert_keywords=("medina de pomar", "villarcayo", "merindad de mena"),
            fotocasa_municipios=("medina-de-pomar", "villarcayo", "espinosa-de-los-monteros", "merindad-de-mena", "torme", "la-pola-de-gordon", "nava-de-ordunte"),
        ),
        Zone(
            id="cantabria_liebana",
            name="Cantabria Liebana / Potes",
            distance_madrid_min=210,
            distance_beach_min=35,
            distance_natural_pools_min=10,
            distance_supermarket_min=5,
            distance_health_center_min=5,
            distance_hospital_min=50,
            fire_risk=FireRisk.BAJO,
            zone_preference=9.0,
            flood_risk=FloodRisk.MEDIO,  # confluencia Deva-Quiviesa, inundacion grave 2010
            price_min=270_000,
            price_max=350_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-potes.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-potes/habitaciones-3/jardin/",
            ),
                        has_coast=True,
            idealista_alert_keywords=("potes", "liebana", "camaleno"),
            fotocasa_municipios=("potes", "camaleno", "liebana", "cabezón-de-liebana", "cillorigo-de-liebana", "vega-de-liebana"),
        ),
        Zone(
            id="asturias_oriente",
            name="Asturias oriental (Villaviciosa, Ribadesella, Colunga)",
            distance_madrid_min=255,
            distance_beach_min=5,
            distance_natural_pools_min=15,
            distance_supermarket_min=8,
            distance_health_center_min=10,
            distance_hospital_min=40,
            fire_risk=FireRisk.MEDIO,
            zone_preference=9.0,
            flood_risk=FloodRisk.BAJO_MEDIO,  # rias atlanticas, bocas Sella/Villaviciosa
            price_min=200_000,
            price_max=450_000,
            fotocasa_search_urls=(),
            habitaclia_search_urls=(
                "https://www.habitaclia.com/casas-villaviciosa.htm",
                "https://www.habitaclia.com/casas-ribadesella.htm",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-villaviciosa/habitaciones-3/jardin/",
                "https://www.pisos.com/venta/casas-ribadesella/habitaciones-3/jardin/",
            ),
                        has_coast=True,
            idealista_alert_keywords=("villaviciosa", "ribadesella", "colunga", "lastres"),
            fotocasa_municipios=("villaviciosa", "ribadesella", "colunga", "lastres", "arriondas", "nava", "parres", "caravia"),
        ),
    ]
}
