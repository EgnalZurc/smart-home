"""
Configuración de las 12 zonas candidatas del estudio (Fase 1).
Las URLs de búsqueda se rellenan con patrones reales de cada portal.
"""

from models import FireRisk, Zone

# ---------------------------------------------------------------------------
# Las 12 zonas con mayor puntuación del estudio peninsular
# Preferencias personales (P11, máx 9): especificadas por el usuario
# ---------------------------------------------------------------------------

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
            zone_preference=5.0,           # P11
            price_min=59_000,
            price_max=259_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/zamora/todas-las-zonas/l"
                "?minRooms=3&maxPrice=270000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-zamora_provincia/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("zamora", "arcenillas", "villaralbo", "morales del vino"),
        ),

        Zone(
            id="castellon_costa_norte",
            name="Castellón costa norte (Vinaròs, Benicarló, Peñíscola)",
            distance_madrid_min=225,
            distance_beach_min=5,
            distance_natural_pools_min=30,
            distance_supermarket_min=5,
            distance_health_center_min=5,
            distance_hospital_min=8,
            fire_risk=FireRisk.MUY_BAJO,
            zone_preference=6.0,           # P11
            price_min=250_000,
            price_max=450_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/castellon/vinaros-benicarlo-peniscola/l"
                "?minRooms=3&maxPrice=320000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-vinaros/habitaciones-3/jardin/",
                "https://www.pisos.com/venta/casas-benicarlo/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("vinaròs", "vinaros", "benicarló", "benicarlo", "peñíscola"),
        ),

        Zone(
            id="salamanca_alrededores",
            name="Salamanca alrededores capital (Doñinos, Aldearrubia, Villamayor)",
            distance_madrid_min=120,
            distance_beach_min=None,
            distance_natural_pools_min=45,
            distance_supermarket_min=8,
            distance_health_center_min=8,
            distance_hospital_min=12,
            fire_risk=FireRisk.NULO,
            zone_preference=5.0,           # P11
            price_min=183_000,
            price_max=299_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/salamanca/todas-las-zonas/l"
                "?minRooms=3&maxPrice=270000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-salamanca/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("doñinos", "aldearrubia", "villamayor", "carbajosa"),
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
            zone_preference=7.0,           # P11
            price_min=208_000,
            price_max=300_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/la-rioja/todas-las-zonas/l"
                "?minRooms=3&maxPrice=270000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-villamediana_de_iregua/habitaciones-3/jardin/",
                "https://www.pisos.com/venta/casas-alberite/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("alberite", "navarrete", "fuenmayor", "villamediana"),
        ),

        Zone(
            id="valencia_costa_norte",
            name="Valencia costa norte (Sagunto, Canet d'En Berenguer, Puçol)",
            distance_madrid_min=210,
            distance_beach_min=5,
            distance_natural_pools_min=15,
            distance_supermarket_min=5,
            distance_health_center_min=5,
            distance_hospital_min=8,
            fire_risk=FireRisk.MUY_BAJO,
            zone_preference=6.0,           # P11
            price_min=250_000,
            price_max=400_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/valencia/sagunto-canet/l"
                "?minRooms=3&maxPrice=320000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-sagunto/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("sagunto", "canet d'en berenguer", "puçol"),
        ),

        Zone(
            id="palencia_alrededores",
            name="Palencia alrededores (Venta de Baños, Grijota, Reinoso)",
            distance_madrid_min=140,
            distance_beach_min=None,
            distance_natural_pools_min=60,
            distance_supermarket_min=8,
            distance_health_center_min=8,
            distance_hospital_min=18,
            fire_risk=FireRisk.NULO,
            zone_preference=5.0,           # P11
            price_min=159_000,
            price_max=207_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/palencia/todas-las-zonas/l"
                "?minRooms=3&maxPrice=220000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-palencia/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("venta de baños", "grijota", "reinoso", "palencia"),
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
            zone_preference=6.0,           # P11
            price_min=100_000,
            price_max=200_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/navarra/tudela/l"
                "?minRooms=3&maxPrice=220000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-tudela/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("tudela", "cadreita", "valtierra", "ribera navarra"),
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
            zone_preference=6.0,           # P11
            price_min=120_000,
            price_max=220_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/burgos/aranda-de-duero/l"
                "?minRooms=3&maxPrice=230000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-burgos/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("aranda de duero", "lerma", "peñaranda de duero"),
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
            zone_preference=4.0,           # P11
            price_min=180_000,
            price_max=250_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/valladolid/todas-las-zonas/l"
                "?minRooms=3&maxPrice=260000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-valladolid_provincia/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("villaturiel", "santa maria del condado", "mansilla"),
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
            zone_preference=4.0,           # P11
            price_min=185_000,
            price_max=285_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/cuenca/todas-las-zonas/l"
                "?minRooms=3&maxPrice=290000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-cuenca/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("sotos", "arcas", "pernalosas", "cuenca"),
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
            zone_preference=6.0,           # P11
            price_min=100_000,
            price_max=230_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/burgos/medina-de-pomar/l"
                "?minRooms=3&maxPrice=240000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-burgos/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("medina de pomar", "villarcayo", "merindad de mena"),
        ),

        Zone(
            id="cantabria_liebana",
            name="Cantabria Liébana / Potes",
            distance_madrid_min=210,
            distance_beach_min=35,
            distance_natural_pools_min=10,
            distance_supermarket_min=5,
            distance_health_center_min=5,
            distance_hospital_min=50,
            fire_risk=FireRisk.BAJO,
            zone_preference=9.0,           # P11 — la preferida
            price_min=270_000,
            price_max=350_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/cantabria/liebana/l"
                "?minRooms=3&maxPrice=320000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-liebana/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("potes", "liébana", "liebana", "camaleño"),
        ),

        Zone(
            id="asturias_oriente",
            name="Asturias oriental (Villaviciosa, Ribadesella, Colunga)",
            distance_madrid_min=255,       # sin peaje por A-66+N-634 ~4h15
            distance_beach_min=5,          # playa directa en toda la costa
            distance_natural_pools_min=15, # pozas Picos, playas fluviales, pozas costeras
            distance_supermarket_min=8,
            distance_health_center_min=10,
            distance_hospital_min=40,      # H. Cabueñes Gijón ~35-45min
            fire_risk=FireRisk.MEDIO,      # oriente: moderado (no el occidente extremo)
            zone_preference=9.0,           # P11 — preferencia máxima indicada
            price_min=200_000,
            price_max=450_000,
            fotocasa_search_urls=(
                "https://www.fotocasa.es/es/comprar/casas/asturias/villaviciosa-ribadesella/l"
                "?minRooms=3&maxPrice=320000",
            ),
            pisos_search_urls=(
                "https://www.pisos.com/venta/casas-villaviciosa/habitaciones-3/jardin/",
                "https://www.pisos.com/venta/casas-ribadesella/habitaciones-3/jardin/",
            ),
            idealista_alert_keywords=("villaviciosa", "ribadesella", "colunga", "lastres"),
        ),
    ]
}
