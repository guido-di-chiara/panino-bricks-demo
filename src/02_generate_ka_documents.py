"""Step 02 - Generate synthetic KA PDF documents and upload to a Databricks Volume.

Creates 6 realistic Italian PDF documents for RAG ingestion by the Knowledge Assistant.
Requires: pip install -r requirements.txt
Catalog/schema and branding come from the repo-root config.py (single source of truth).

NOTE on FPDF: PDFs use the latin-1 core fonts, so the document bodies must stay
ASCII (no smart quotes, no em-dashes, no euro symbol; use straight quotes, "EUR",
and "-" bullets). Do not "improve" the text with Unicode punctuation.

Run standalone:  python src/02_generate_ka_documents.py --profile <ws> --catalog <cat>
Run in-workspace: import and call main() (profile ignored under ambient auth).
"""
import io
import os
import sys
import argparse
from fpdf import FPDF

# Make the repo-root config + src/_common importable regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root (config.py)
sys.path.insert(0, _HERE)                    # src/ (_common.py)

# =============================================================================
# DATABRICKS SDK CONNECTION
# =============================================================================
parser = argparse.ArgumentParser(description="Generate Panino Bricks KA PDF documents")
parser.add_argument("--profile", default=None, help="Databricks CLI profile (omit in-workspace)")
parser.add_argument("--catalog", default=None, help="Override PB_CATALOG (else config default / env)")
parser.add_argument("--schema", default=None, help="Override PB_SCHEMA (else config default / env)")
args = parser.parse_args()

if args.catalog:
    os.environ["PB_CATALOG"] = args.catalog
if args.schema:
    os.environ["PB_SCHEMA"] = args.schema

from config import CATALOG, SCHEMA, BRAND_NAME, KA_VOLUME_NAME, KA_VOLUME_PATH  # noqa: E402
from _common import get_workspace_client  # noqa: E402

VOLUME_PATH = KA_VOLUME_PATH

print("Connecting to Databricks workspace...")
w = get_workspace_client(args.profile)
print(f"  Host: {w.config.host}")

# Ensure the KA documents Volume exists (schema is created by step 01).
from databricks.sdk.service.catalog import VolumeType  # noqa: E402

try:
    w.volumes.create(
        catalog_name=CATALOG,
        schema_name=SCHEMA,
        name=KA_VOLUME_NAME,
        volume_type=VolumeType.MANAGED,
    )
    print(f"  Created volume {CATALOG}.{SCHEMA}.{KA_VOLUME_NAME}")
except Exception as e:
    print(f"  Volume {CATALOG}.{SCHEMA}.{KA_VOLUME_NAME} already exists ({type(e).__name__})")


# =============================================================================
# PDF HELPER
# =============================================================================
class PaninoBricksPDF(FPDF):
    """Custom PDF with Panino Bricks branding."""

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 60, 20)
        self.cell(0, 8, f"{BRAND_NAME}  |  Documento Interno", align="R")
        self.ln(4)
        self.set_draw_color(100, 60, 20)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"{BRAND_NAME} Confidenziale  -  Pagina {self.page_no()}/{{nb}}", align="C")


def create_pdf(title, sections):
    """Create a styled PDF from a title and list of (heading, body) sections.

    Returns the PDF as bytes.
    """
    pdf = PaninoBricksPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title page content
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(80, 40, 10)
    pdf.ln(30)
    pdf.multi_cell(0, 12, title, align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 8, f"{BRAND_NAME} S.r.l.  |  In vigore dal 2026", align="C")
    pdf.ln(4)
    pdf.multi_cell(0, 8, "CONFIDENZIALE - Solo per uso interno", align="C")

    for heading, body in sections:
        pdf.add_page()
        # Section heading
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(80, 40, 10)
        pdf.cell(0, 10, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_draw_color(100, 60, 20)
        pdf.line(10, pdf.get_y(), 120, pdf.get_y())
        pdf.ln(6)

        # Body text
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(40, 40, 40)
        for line in body.split("\n"):
            stripped = line.strip()
            if not stripped:
                pdf.ln(4)
            elif stripped.startswith("## "):
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 13)
                pdf.set_text_color(80, 40, 10)
                pdf.cell(0, 8, stripped[3:], new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 11)
                pdf.set_text_color(40, 40, 40)
            elif stripped.startswith("- "):
                # Reset x to left margin and use an explicit full width (epw) — avoids
                # fpdf2 "not enough horizontal space" when x drifted right, and U+2022
                # which core latin-1 fonts can't encode (use a plain "-" bullet).
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pdf.epw, 6, "   -  " + stripped[2:])
            else:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pdf.epw, 6, stripped)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf.getvalue()


# =============================================================================
# DOCUMENT CONTENT
# =============================================================================

manuale_operatore = (
    "Manuale Operatore",
    [
        ("1. Benvenuto in Panino Bricks", """
Benvenuto in Panino Bricks! Siamo una catena italiana di paninoteche premium con 37 sedi in tutta Italia, da Milano a Palermo. La nostra missione e offrire panini artigianali di alta qualita, con materie prime selezionate e un servizio impeccabile e costante in ogni sede.

## I Nostri Valori
- Qualita prima di tutto: usiamo Mortadella IGP, Prosciutto Crudo, Stracciatella di Bufala, Burrata Pugliese, pane fresco artigianale e Tartufo Nero da fornitori selezionati.
- Coerenza: ogni panino deve essere preparato seguendo le procedure operative standard, indipendentemente dalla sede.
- Esperienza del cliente: servizio cordiale ed efficiente, con un tempo medio di preparazione obiettivo di 3-4 minuti.
- Territorio: valorizziamo le specialita regionali italiane e costruiamo un rapporto con i clienti abituali.

## Le Nostre Paninoteche (37 in Italia)
- Lombardia: Milano Navigli, Milano Brera, Milano Isola, Brescia, Monza, Como
- Lazio: Roma Trastevere, Roma Monti, Roma EUR, Roma Prati
- Piemonte: Torino San Salvario, Torino Quadrilatero
- Emilia-Romagna: Bologna, Parma, Modena, Rimini
- Veneto: Verona, Padova, Venezia Mestre, Vicenza
- Toscana: Firenze, Pisa
- Trentino-Alto Adige: Trento, Bolzano (grande apertura recente)
- Altre regioni: Napoli, Salerno (Campania); Genova (Liguria); Bari, Lecce (Puglia); Trieste (Friuli); Palermo, Catania (Sicilia); Perugia (Umbria); Cagliari (Sardegna); Ancona (Marche); Pescara (Abruzzo)
"""),
        ("2. Apertura e Setup del Banco", """
Ogni turno inizia con un setup accurato della postazione. Completa la seguente checklist prima dell'apertura del punto vendita.

## Apertura Mattutina (30 minuti prima dell'apertura)
- Accendi la piastra e il tostapane e portali a temperatura di esercizio.
- Verifica e disponi i salumi affettati di giornata: Mortadella IGP, Prosciutto Crudo, Salame Milano, Speck Alto Adige, Culatello di Zibello. Affetta al momento dove possibile per garantire freschezza.
- Controlla i latticini nel banco refrigerato: Mozzarella Fiordilatte, Stracciatella di Bufala, Burrata Pugliese, Pecorino Romano. Rabbocca dalla cella se sotto soglia.
- Disponi il pane fresco consegnato da Forno Artigiano Milano (SUP-003, lead time 1 giorno): Michette, Focaccia Genovese, Ciabatta, Pane ai Cereali, Piadina, Pane Casereccio.
- Prepara la postazione verdure e aggiunte: Friarielli, Rucola, Melanzane Grigliate, Funghi Trifolati, Pomodori Secchi, Cipolla Caramellata.
- Disponi le salse: Maionese, Senape, Salsa Tartufata, Pesto Genovese.
- Verifica le specialita: Tartufo Nero, Pistacchio di Bronte, Tonno sott'olio.
- Accendi il sistema POS e verifica la connessione alla piattaforma di ordinazione tramite App Mobile.

## Layout del Banco
- Postazione 1 (Ordini): terminale POS, area preparazione carta alimentare, espositore.
- Postazione 2 (Preparazione): taglieri, affettatrice, salse in dosatori, banco salumi e formaggi.
- Postazione 3 (Cottura): piastra, tostapane, forno per riscaldo e gratinatura.
- Postazione 4 (Confezionamento e Consegna): incarto in carta alimentare, schermo ordini, bancone ritiro.
"""),
        ("3. Standard di Preparazione dei Panini", """
Tutti i panini devono seguire la ricetta standard con dosi precise. Le personalizzazioni sono consentite nell'ambito delle opzioni definite.

## Taglie
- Junior: -1.00 EUR rispetto al prezzo base. Porzione ridotta, ideale per bambini o pausa leggera.
- Classico: prezzo base. Porzione standard.
- Maxi: +1.50 EUR rispetto al prezzo base. Porzione abbondante, doppia farcitura di salume.

## Scelta del Pane
- Michetta: pane croccante milanese, ottimo per i Classici.
- Ciabatta: alveolata e leggera.
- Focaccia: la Focaccia Genovese, saporita e morbida.
- Pane ai Cereali: ricco di semi, per chi cerca un gusto rustico.
- Piadina: per la linea Regionale e farciture sfiziose.
- Pane Casereccio: pane rustico a lievitazione naturale.

## Tostatura
- Tostato: pane scaldato al tostapane, croccante fuori.
- Non Tostato: pane servito a temperatura ambiente.
- Caldo alla Piastra: schiacciato e scaldato sulla piastra (ideale per Porchetta, 'Nduja, Melanzane & Scamorza).
- Freddo: per panini con ingredienti delicati come Stracciatella o Burrata, che non vanno scaldati.

## Salse
- Nessuna: panino senza salsa aggiunta.
- Maionese: inclusa, nessun sovrapprezzo.
- Senape: inclusa, nessun sovrapprezzo.
- Salsa Tartufata: +1.50 EUR. Da abbinare ai panini Gourmet.
- Pesto: +0.50 EUR. Pesto Genovese, ottimo con Caprese e Vegetariani.

## Regole di Farcitura
- Affetta i salumi sottili e disponili a onde per dare volume.
- I formaggi a pasta filata (Mozzarella, Scamorza) vanno gratinati al forno quando previsto caldo.
- Stracciatella e Burrata vanno aggiunte a freddo, sempre a fine farcitura.
- Verifica sempre con il cliente: taglia, pane, tostatura, salsa ed eventuali aggiunte.
"""),
        ("4. Standard di Servizio al Cliente", """
Panino Bricks punta a un'esperienza cliente di prim'ordine. Segui queste linee guida in ogni interazione.

## Accoglienza e Presa Ordine
- Accogli ogni cliente entro 5 secondi dall'arrivo al bancone: "Benvenuto da Panino Bricks!"
- Per i nuovi clienti, illustra brevemente le categorie del menu: Classici, Gourmet, Vegetariani, Regionali, Stagionali e Premium.
- Suggerisci i piu venduti se richiesto: Mortadella & Pistacchio (tra i nostri preferiti), Tartufo & Stracciatella, Porchetta di Ariccia.
- Conferma sempre le personalizzazioni: taglia, pane, tostatura, salsa e aggiunte.
- Ripeti l'ordine completo al cliente prima di procedere con il pagamento. Ricorda che l'IVA ristorazione applicata e del 10%.

## Canali di Ordine
Riceviamo ordini attraverso tre canali:
- In negozio (55% degli ordini): ordinazione diretta al bancone tramite POS.
- App Mobile (35% degli ordini): gli ordini compaiono sullo schermo di preparazione. Prepara e tieni pronto per il ritiro.
- Online/delivery (10% degli ordini): ordini dei partner di consegna. Confeziona con incarto sigillato e sacchetti termici.

## Gestione dei Reclami
- Ascolta attivamente senza interrompere.
- Scusati sinceramente e offri di rifare il panino immediatamente.
- Se l'ordine e errato, rifallo senza costi e lascia al cliente l'originale.
- Per problemi di qualita, offri un buono per un panino omaggio alla visita successiva.
- Registra tutti i reclami nel report di turno per la revisione del responsabile.
- IMPORTANTE: per qualsiasi reclamo legato ad allergie, segui la procedura dedicata della Politica di Sicurezza Alimentare (HACCP).

## Programma Fedelta
- Livello Bronze: 50-200 punti
- Livello Silver: 200-800 punti
- Livello Gold: 800-2.500 punti
- Livello Platinum: 2.500-8.000 punti
- I clienti accumulano 1 punto per ogni euro speso. I livelli piu alti sbloccano aggiunte omaggio, sorprese di compleanno e promozioni esclusive.
- Chiedi sempre se il cliente ha un account fedelta e ricordagli di registrare l'acquisto tramite l'App Mobile.

## Promozioni Attive
- Aperitivo (17-19): sconto su panini selezionati nella fascia serale.
- Lunedi del Tartufo: offerta sulla linea con Tartufo.
- Punti Fedelta Doppi: punti raddoppiati in giornate dedicate.
- Sconto Studenti: agevolazione con documento valido.
- Prendi 5 Paghi 4: il quinto panino in omaggio.
"""),
        ("5. Procedure di Chiusura", """
Le procedure di chiusura garantiscono che il punto vendita sia pulito, sicuro e pronto per il giorno successivo.

## Checklist di Fine Giornata
- Riponi salumi e formaggi affettati residui in contenitori sigillati nel banco refrigerato, etichettati con la data.
- Smaltisci gli ingredienti freschi deperibili che hanno superato la giornata (verdure grigliate, salse aperte oltre i limiti).
- Pulisci e sanifica l'affettatrice smontando le parti a contatto, la piastra e il tostapane.
- Pulisci tutti i piani di lavoro, i taglieri e la postazione salse con sanificante alimentare.
- Svuota e pulisci il banco refrigerato e verifica che la temperatura resti sotto i 4 gradi C.
- Pulisci il forno e la piastra da residui e grassi.
- Spazza e lava tutti i pavimenti, anche dietro il bancone.
- Rifornisci carta alimentare, tovaglioli e sacchetti per il turno del mattino.
- Conta la cassa e completa la riconciliazione giornaliera sul POS.
- Inserisci l'allarme e chiudi tutte le porte.

## Note di Inventario per la Chiusura
- Controlla che le scorte di pane siano sufficienti per il mattino. Se le Michette sono in esaurimento, segnalalo sul foglio di preparazione del mattino (Forno Artigiano Milano consegna in 1 giorno).
- Controlla le scorte di salumi. Se Mortadella IGP o Prosciutto Crudo sono sotto soglia, invia una richiesta di riordino a Salumificio Emiliano S.r.l. (SUP-001, lead time 4 giorni).
- Registra eventuali problemi alle attrezzature nel registro manutenzione per il responsabile.
"""),
    ],
)

ricettario_panini = (
    "Ricettario Panini - Procedure Standard",
    [
        ("1. Linea Classici", """
La linea Classici e il cuore dell'offerta Panino Bricks e rappresenta la maggior parte delle vendite. Tutti i panini Classici usano salumi selezionati e latticini freschi.

## Mortadella & Pistacchio
Tra i nostri panini piu amati.
- Pane consigliato: Michetta
- Farcitura: Mortadella IGP (abbondante, a onde), granella di Pistacchio di Bronte, un velo di Stracciatella di Bufala
- Tostatura consigliata: Non Tostato o Caldo alla Piastra
- Allergeni: glutine (pane), latte (stracciatella), frutta a guscio (pistacchio)

## Prosciutto Crudo & Mozzarella
- Pane consigliato: Ciabatta
- Farcitura: Prosciutto Crudo, Mozzarella Fiordilatte, filo d'olio
- Tostatura: Non Tostato
- Allergeni: glutine, latte

## Cotto e Funghi
- Pane consigliato: Michetta
- Farcitura: prosciutto cotto, Funghi Trifolati, Mozzarella Fiordilatte
- Tostatura: Caldo alla Piastra (per filare la mozzarella)
- Allergeni: glutine, latte

## Salame & Pecorino
- Pane consigliato: Pane Casereccio
- Farcitura: Salame Milano, scaglie di Pecorino Romano, Rucola
- Tostatura: Non Tostato
- Allergeni: glutine, latte

## Caprese
- Pane consigliato: Focaccia Genovese
- Farcitura: Mozzarella Fiordilatte, pomodoro, basilico, filo d'olio
- Salsa consigliata: Pesto (+0.50 EUR)
- Allergeni: glutine, latte (e frutta a guscio se aggiunto il pesto)

## Tonno e Cipolla
- Pane consigliato: Michetta
- Farcitura: Tonno sott'olio, Cipolla Caramellata, Maionese
- Tostatura: Non Tostato
- Allergeni: glutine, pesce (tonno), uova (maionese)
"""),
        ("2. Linea Gourmet", """
La linea Gourmet propone abbinamenti ricercati con ingredienti premium e prezzi piu alti.

## Tartufo & Stracciatella
- Pane consigliato: Pane Casereccio o Ciabatta
- Farcitura: Stracciatella di Bufala, lamelle di Tartufo Nero, Salsa Tartufata (+1.50 EUR)
- Tostatura: Freddo (la stracciatella non va scaldata)
- Allergeni: glutine, latte
- Nota: panino di punta del "Lunedi del Tartufo".

## Culatello & Burrata
- Pane consigliato: Ciabatta
- Farcitura: Culatello di Zibello, Burrata Pugliese, Rucola
- Tostatura: Freddo
- Allergeni: glutine, latte

## 'Nduja & Friarielli
- Pane consigliato: Pane Casereccio
- Farcitura: 'Nduja piccante spalmata, Friarielli saltati, Mozzarella Fiordilatte
- Tostatura: Caldo alla Piastra
- Allergeni: glutine, latte

## Porchetta di Ariccia
- Pane consigliato: Ciabatta o Pane Casereccio
- Farcitura: Porchetta di Ariccia a fette spesse, filo d'olio, pepe
- Tostatura: Caldo alla Piastra
- Allergeni: glutine

## Roast Beef & Rucola
- Pane consigliato: Pane ai Cereali
- Farcitura: roast beef, Rucola, scaglie di Pecorino Romano, Maionese
- Tostatura: Non Tostato
- Allergeni: glutine, latte, uova (maionese)

## Speck & Brie
- Pane consigliato: Pane ai Cereali
- Farcitura: Speck Alto Adige, brie, Rucola
- Tostatura: Caldo alla Piastra
- Allergeni: glutine, latte
"""),
        ("3. Linea Vegetariani", """
Panini senza carne ne pesce, ricchi di verdure e latticini.

## Melanzane & Scamorza
- Pane consigliato: Focaccia Genovese
- Farcitura: Melanzane Grigliate, scamorza, Pomodori Secchi
- Tostatura: Caldo alla Piastra (per fondere la scamorza)
- Allergeni: glutine, latte

## Zucchine Grigliate & Hummus
- Pane consigliato: Pane ai Cereali
- Farcitura: zucchine grigliate, hummus, Rucola
- Tostatura: Non Tostato
- Allergeni: glutine
- Nota: tra i pochi panini senza latte; verificare comunque la contaminazione crociata.

## Caprese Vegana
- Pane consigliato: Ciabatta
- Farcitura: mozzarella vegetale, pomodoro, basilico
- Salsa: Pesto (+0.50 EUR) contiene frutta a guscio; offrire alternativa se richiesto
- Tostatura: Freddo
- Allergeni: glutine (e frutta a guscio se aggiunto il pesto)

## Friggitelli & Stracciatella
- Pane consigliato: Pane Casereccio
- Farcitura: friggitelli saltati, Stracciatella di Bufala
- Tostatura: Freddo
- Allergeni: glutine, latte
"""),
        ("4. Linea Regionali", """
Specialita del territorio italiano, ognuna legata a una tradizione locale.

## Lampredotto alla Fiorentina
- Pane consigliato: Michetta (semelle)
- Farcitura: lampredotto, salsa verde, pepe; pane bagnato nel brodo
- Tostatura: Caldo
- Allergeni: glutine, sedano (salsa verde)

## Pane e Panelle
- Pane consigliato: Michetta morbida
- Farcitura: panelle di ceci fritte, limone
- Tostatura: Caldo
- Allergeni: glutine

## Piadina Romagnola
- Pane: Piadina
- Farcitura: prosciutto crudo, squacquerone, Rucola
- Tostatura: Caldo alla Piastra
- Allergeni: glutine, latte

## Puccia Salentina
- Pane: Puccia (rientra nella linea Regionale, servita come pane dedicato)
- Farcitura: verdure grigliate, formaggio, salumi a scelta
- Tostatura: Caldo
- Allergeni: glutine, latte

## Focaccia di Recco
- Pane: Focaccia (sottile, ripiena di formaggio)
- Farcitura: crescenza filante
- Tostatura: Caldo al forno
- Allergeni: glutine, latte
"""),
        ("5. Linee Stagionali e Premium", """
## Linea Stagionali
Panini disponibili solo in determinati periodi dell'anno.

## Zucca & Speck (autunno)
- Pane consigliato: Pane ai Cereali
- Farcitura: crema di zucca, Speck Alto Adige
- Tostatura: Caldo alla Piastra
- Allergeni: glutine
- Nota: protagonista della promo "Speciale Autunno Zucca".

## Asparagi & Uovo (primavera)
- Pane consigliato: Ciabatta
- Farcitura: asparagi grigliati, uovo, scaglie di Pecorino Romano
- Tostatura: Caldo
- Allergeni: glutine, uova, latte

## Caprese Estiva (estate)
- Pane consigliato: Focaccia Genovese
- Farcitura: Mozzarella Fiordilatte, pomodoro fresco, basilico, Pesto
- Tostatura: Freddo
- Allergeni: glutine, latte, frutta a guscio (pesto)
- Nota: protagonista della "Promo Caprese Estiva".

## Tartufo Bianco d'Alba (autunno, edizione limitata)
- Pane consigliato: Pane Casereccio
- Farcitura: Stracciatella di Bufala, lamelle di tartufo bianco d'Alba
- Tostatura: Freddo
- Allergeni: glutine, latte

## Linea Premium
Offerte di fascia alta con ingredienti pregiati.

## Wagyu & Cipolla Caramellata
- Pane consigliato: Pane Casereccio
- Farcitura: fettine di Wagyu scottato, Cipolla Caramellata, Rucola
- Tostatura: Caldo alla Piastra
- Allergeni: glutine

## Baccala Mantecato
- Pane consigliato: Ciabatta
- Farcitura: baccala mantecato, prezzemolo, pepe
- Tostatura: Freddo
- Allergeni: glutine, pesce (baccala), latte

## Vitello Tonnato
- Pane consigliato: Michetta
- Farcitura: fettine di vitello, salsa tonnata, capperi
- Tostatura: Non Tostato
- Allergeni: glutine, pesce (tonno nella salsa), uova (salsa tonnata)

## Senza Glutine - Crudo & Mozzarella
- Pane: Pane Senza Glutine Certificato (fornitura dedicata, confezionato singolarmente)
- Farcitura: prosciutto crudo, mozzarella fiordilatte
- Tostatura: Non Tostato (NON usare la piastra comune: usare la piastra/area dedicata senza glutine)
- Allergeni: latte (mozzarella). NON contiene glutine se preparato secondo il protocollo dedicato.
- IMPORTANTE: e' l'UNICO panino adatto ai clienti celiaci. Va preparato in postazione
  dedicata, con utensili, taglieri e guanti separati, per evitare la contaminazione crociata.
  Tutti gli altri panini del menu contengono glutine e NON sono adatti ai celiaci.
"""),
        ("6. Aggiunte e Regole di Personalizzazione", """
## Aggiunte Disponibili
Il cliente puo arricchire qualsiasi panino con le seguenti aggiunte:
- Doppia Mozzarella (latte)
- 'Nduja Piccante
- Stracciatella (latte)
- Friarielli
- Funghi Trifolati
- Rucola
- Pomodori Secchi
- Melanzane Grigliate
- Salsa Tartufata (latte assente, ma verificare lotto)
- Pesto Genovese (frutta a guscio: pinoli/anacardi)
- Burrata (latte)
- Cipolla Caramellata

## Regole di Personalizzazione
- Taglia: Junior (-1.00 EUR), Classico (base), Maxi (+1.50 EUR).
- Pane: scelta libera tra Michetta, Ciabatta, Focaccia, Pane ai Cereali, Piadina, Pane Casereccio.
- Tostatura: Tostato, Non Tostato, Caldo alla Piastra, Freddo. Sconsigliare la tostatura calda per panini con Stracciatella o Burrata.
- Salsa: Nessuna, Maionese, Senape (incluse); Salsa Tartufata (+1.50 EUR); Pesto (+0.50 EUR).

## Standard di Qualita
- I panini devono essere serviti entro 60 secondi dalla preparazione.
- Salumi affettati al momento dove possibile; mai servire salume ossidato o asciutto.
- Latticini freschi (Stracciatella, Burrata) sempre aggiunti per ultimi e a freddo.
- Il pane caldo non deve risultare bruciato: regola tostapane e piastra a temperatura corretta.
- Verifica sempre l'ordine personalizzato prima del confezionamento.
"""),
    ],
)

sicurezza_alimentare_haccp = (
    "Politica di Sicurezza Alimentare (HACCP)",
    [
        ("1. Principi Generali di Sicurezza Alimentare", """
Panino Bricks e impegnata a mantenere i piu alti standard di sicurezza alimentare in tutte le 37 sedi in Italia. Tutti i dipendenti devono completare la formazione sulla sicurezza alimentare entro la prima settimana di lavoro e seguire corsi di aggiornamento annuali.

## Conformita Normativa
- Tutte le sedi Panino Bricks operano in conformita al sistema HACCP (Hazard Analysis and Critical Control Points - Analisi dei Pericoli e Punti Critici di Controllo) e al Regolamento CE 852/2004 sull'igiene dei prodotti alimentari.
- Ogni sede mantiene il proprio manuale di autocontrollo HACCP aggiornato e accessibile.
- I controlli ASL devono trovare sempre la sede in regola; eventuali non conformita richiedono un piano di azioni correttive immediato.

## Principi Fondamentali
- Nel dubbio, scartalo. Non servire mai un prodotto che possa essere stato contaminato o conservato in modo improprio.
- L'igiene personale non e negoziabile. Il lavaggio delle mani e obbligatorio ogni 30 minuti e tra un'attivita e l'altra.
- FIFO (First In, First Out): usa sempre per prima la merce in scadenza piu vicina.
- Il controllo della temperatura e critico. I deperibili vanno conservati a 4 gradi C o meno; i prodotti caldi vanno mantenuti a 60 gradi C o piu.
"""),
        ("2. Conservazione degli Ingredienti e Catena del Freddo", """
## Dispensa (15-20 gradi C, bassa umidita)
- Pane (Michette, Focaccia Genovese, Ciabatta, Pane ai Cereali, Pane Casereccio): consegnato fresco ogni giorno da Forno Artigiano Milano (SUP-003, lead time 1 giorno). Consumare in giornata.
- Tonno sott'olio e conserve (Conserve Mediterranee, SUP-008, lead time 5 giorni): contenitori sigillati, luogo fresco e asciutto.
- Carta alimentare e packaging (EcoPack Imballaggi, SUP-007, lead time 7 giorni): area pulita e asciutta.

## Banco Refrigerato e Cella (0-4 gradi C)
- Salumi (Salumificio Emiliano S.r.l., SUP-001, lead time 4 giorni): Mortadella IGP, Prosciutto Crudo, Salame Milano, Speck Alto Adige, Culatello di Zibello. Conservare incartati, consumare entro la data indicata.
- Latticini (Caseificio del Sud, SUP-002, lead time 2 giorni): Mozzarella Fiordilatte, Pecorino Romano, Stracciatella di Bufala, Burrata Pugliese. Stracciatella e Burrata vanno consumate entro 2 giorni dall'apertura per la massima freschezza.
- Verdure e ortaggi (Ortofrutta Fresca S.p.A., SUP-004, lead time 2 giorni): Friarielli, Rucola, Melanzane, Funghi Champignon. Consumare entro pochi giorni.
- Salse aperte (Salse & Condimenti Italia, SUP-006, lead time 3 giorni): Maionese, Pesto Genovese. Rispettare le date di consumo dopo apertura.

## Specialita (conservazione dedicata)
- Tartufo Nero e specialita (Tartufi & Specialita Alba, SUP-005, lead time 6 giorni): conservare il tartufo in contenitore ermetico in frigo, avvolto in carta, e consumarlo rapidamente per preservarne l'aroma.

## Catena del Freddo
- I salumi e i latticini non devono mai interrompere la catena del freddo. Al ricevimento merce, verifica la temperatura del trasporto e registra eventuali anomalie.
- Se il banco refrigerato supera i 4 gradi C, ispeziona tutti i contenuti. Scarta i latticini rimasti sopra i 4 gradi C per piu di 2 ore.
- Registra la temperatura del banco refrigerato e della cella due volte per turno (apertura e meta turno) sul modulo di monitoraggio HACCP.
"""),
        ("3. Gestione Allergeni", """
La corretta gestione degli allergeni e fondamentale. In Italia, ai sensi del Regolamento UE 1169/2011, le informazioni sugli allergeni devono essere sempre disponibili al cliente. Di seguito gli allergeni presenti negli ingredienti Panino Bricks.

## Glutine (cereali)
- Presente in TUTTI i pani standard: Michette, Focaccia Genovese, Ciabatta, Pane ai Cereali, Piadina, Pane Casereccio.
- IMPORTANTE: i panini standard Panino Bricks contengono glutine per impostazione predefinita. NON garantiamo l'assenza di glutine su questi prodotti: il rischio di contaminazione crociata in cucina e elevato (stessa piastra, stessi taglieri, farina nell'aria).

## Quali panini sono adatti ai clienti celiaci?
- E' disponibile UN panino adatto ai celiaci: il "Senza Glutine - Crudo & Mozzarella" (PRD-029), preparato con Pane Senza Glutine Certificato.
- Questo panino e' preparato in una POSTAZIONE DEDICATA, con utensili, taglieri, guanti e piastra separati, per evitare la contaminazione crociata.
- Tutti gli ALTRI panini del menu contengono glutine e NON sono adatti ai celiaci.
- Quando un cliente celiaco chiede un panino: proponi il "Senza Glutine - Crudo & Mozzarella" e conferma che e' preparato nel protocollo dedicato senza glutine. Per ogni altro panino, comunica che contiene glutine.

## Latte / Lattosio
- Presente in: Mozzarella Fiordilatte, Stracciatella di Bufala, Burrata Pugliese, Pecorino Romano, scamorza, brie.
- Panini interessati: tutta la linea con formaggi (es. Mortadella & Pistacchio con stracciatella, Caprese, Tartufo & Stracciatella, Culatello & Burrata, Speck & Brie, Melanzane & Scamorza).

## Frutta a Guscio
- Presente in: Pistacchio di Bronte (Mortadella & Pistacchio); Pesto Genovese (contiene pinoli e talvolta anacardi).
- Attenzione alla contaminazione crociata sul piano di preparazione del pesto e della granella di pistacchio.

## Pesce
- Presente in: Tonno sott'olio (Tonno e Cipolla, salsa tonnata del Vitello Tonnato); Baccala (Baccala Mantecato).

## Uova
- Presente in: Maionese (Tonno e Cipolla, Roast Beef & Rucola), uovo (Asparagi & Uovo), salsa tonnata (Vitello Tonnato).

## Altri Allergeni
- Solfiti: possono essere presenti in alcune conserve e salumi; verificare le etichette dei fornitori.
- Sedano e Senape: presenti in alcune salse (es. salsa verde del Lampredotto, Senape come condimento).

## Come Dedurre gli Allergeni di un Panino
Per ogni panino, gli allergeni si deducono dagli ingredienti della ricetta nel Ricettario. Esempio pratico: il panino "Mortadella & Pistacchio" contiene glutine (pane), latte (stracciatella) e frutta a guscio (pistacchio); quindi NON e adatto a un cliente con allergia alla frutta a guscio, e NON puo essere garantito a un celiaco.
"""),
        ("4. Gestione Reclami per Allergia e Procedure", """
## Procedura per Richiesta Informazioni Allergeni
- Quando un cliente chiede informazioni sugli allergeni, consulta la scheda allergeni tenuta a ogni postazione POS e le ricette nel Ricettario.
- Comunica sempre con chiarezza, senza minimizzare. In caso di dubbio sulla presenza di un allergene, dichiaralo come possibile.
- Per il glutine: per un cliente celiaco proponi SOLO il "Senza Glutine - Crudo & Mozzarella" (preparato in postazione dedicata). Per tutti gli altri panini NON garantiamo l'assenza di glutine per via della contaminazione crociata: non definirli mai sicuri per un celiaco.

## Procedura per Cliente con Allergia Dichiarata
- Se un cliente segnala un'allergia grave (es. frutta a guscio, pesce), prepara il panino con taglieri, coltelli e piano di lavoro puliti e sanificati.
- Cambia i guanti prima della preparazione.
- Evita ingredienti e salse a rischio: per allergia alla frutta a guscio, escludi Pesto e Pistacchio; per allergia al pesce, escludi Tonno e Baccala; per intolleranza al lattosio/allergia al latte, escludi tutti i formaggi.
- In caso di dubbio sulla sicurezza, declina gentilmente la preparazione anziche rischiare.

## Gestione di una Reazione Allergica
- In caso di reazione allergica di un cliente, allerta immediatamente i soccorsi (112) e il responsabile.
- Non somministrare farmaci se non quelli che il cliente porta con se (es. autoiniettore di adrenalina).
- Documenta l'accaduto nel report di turno e conserva l'incarto e gli ingredienti coinvolti.

## Registro Scarti e Monitoraggio
Ogni sede mantiene un registro giornaliero degli scarti con: prodotto scartato, quantita, motivo (scaduto, qualita, contaminazione), iniziali dell'operatore e orario. Il registro e rivisto settimanalmente dal responsabile di sede.
"""),
        ("5. Igiene, Pulizia e Controlli ASL", """
## Igiene del Personale
- Lavaggio delle mani ogni 30 minuti e a ogni cambio attivita, soprattutto dopo aver maneggiato salumi crudi.
- Uso di guanti monouso e copricapo. Divise pulite a inizio turno.
- Niente gioielli alle mani durante la preparazione.

## Pulizia delle Attrezzature a Contatto con Alimenti
- Affettatrice: smontare e sanificare le parti a contatto a fine giornata e tra salumi diversi quando necessario.
- Taglieri: separare quelli per carne/salumi da quelli per verdure; sanificare dopo ogni uso a rischio.
- Piastra, tostapane e forno: pulire da residui e grassi quotidianamente.
- Banco refrigerato e cella: sanificare ripiani e pareti settimanalmente.

## Preparazione ai Controlli ASL
La sede deve essere sempre pronta a un controllo. Il responsabile verifica settimanalmente:
- Manuale di autocontrollo HACCP aggiornato e accessibile.
- Attestati di formazione alimentare per tutto il personale.
- Moduli di monitoraggio temperature degli ultimi 30 giorni.
- Registro scarti degli ultimi 30 giorni.
- Schede di sicurezza e certificazioni dei fornitori.

## Errori Comuni da Evitare
- Prodotti scaduti in conservazione (controllo date settimanale).
- Mancanza di etichette con data sugli alimenti preparati.
- Interruzione della catena del freddo per salumi e latticini.
- Personale senza copricapo o guanti.
- Concentrazione errata del sanificante.
"""),
    ],
)

guida_franchising = (
    "Guida Operativa Franchising",
    [
        ("1. Panoramica del Franchising Panino Bricks", """
Panino Bricks si espande con un modello di franchising per portare l'esperienza della paninoteca premium in nuovi mercati italiani. Questa guida descrive requisiti, costi e processi per aprire una nuova paninoteca Panino Bricks.

## Il Brand
- Catena italiana di paninoteche artigianali con focus su qualita e specialita regionali.
- Attualmente 37 sedi di proprieta in tutta Italia, da Milano a Palermo, con apertura recente a Bolzano.
- Forte presenza digitale: il 35% degli ordini arriva tramite App Mobile e il 10% tramite online/delivery.
- Programma fedelta a 4 livelli (Bronze, Silver, Gold, Platinum) che alimenta gli acquisti ripetuti.

## L'Opportunita di Franchising
- Diritti di zona esclusivi entro un raggio definito.
- Licenza completa del brand, delle ricette e del sistema operativo.
- Accesso alla rete consolidata di fornitori (8 fornitori selezionati).
- Integrazione con l'App Mobile e il programma fedelta Panino Bricks.
- Formazione e supporto continui dal team operativo Panino Bricks.
"""),
        ("2. Requisiti Finanziari", """
## Investimento Iniziale (stima)
- Diritto di ingresso (fee di franchising): 30.000 EUR
- Ristrutturazione e allestimento locale: 90.000 - 140.000 EUR (variabile per mercato e condizioni del sito)
- Pacchetto attrezzature: 40.000 - 55.000 EUR (piastra, tostapane, affettatrice, forno, banco refrigerato, cella, POS)
- Scorte iniziali: 6.000 - 10.000 EUR
- Insegne e branding: 8.000 - 12.000 EUR
- Capitale circolante (primi 3 mesi): 20.000 - 35.000 EUR
- Investimento totale stimato: 194.000 - 282.000 EUR

## Costi Ricorrenti
- Royalty: 6% del fatturato lordo
- Contributo al fondo marketing: 2% del fatturato lordo
- Canone tecnologico (POS, integrazione App Mobile, programma fedelta): 450 EUR al mese
- Assicurazioni obbligatorie: responsabilita civile, infortuni sul lavoro, danni al locale

## Requisiti Patrimoniali
- Patrimonio netto minimo: 400.000 EUR
- Liquidita minima disponibile: 130.000 EUR
- Storia creditizia soddisfacente
- Esperienza nel settore ristorazione preferibile ma non obbligatoria
"""),
        ("3. Selezione del Sito e Allestimento", """
## Caratteristiche del Sito Ideale
Le paninoteche Panino Bricks funzionano meglio in zone a forte passaggio e con clientela giovane. Le sedi di maggior successo condividono questi tratti:
- Superficie: 60-90 mq
- Posti a sedere: 10-24
- Forte passaggio pedonale: vicino a universita, zone uffici o vie commerciali di tendenza (es. Milano Navigli, Roma Trastevere, Torino San Salvario)
- Visibilita: piano strada con vetrina su strada
- Demografia: aree con significativa popolazione 18-35 anni
- Attivita complementari nelle vicinanze: ristoranti, locali, negozi

## Processo di Approvazione del Sito
- Il franchisee propone 2-3 siti potenziali con dati demografici.
- Il team immobiliare Panino Bricks valuta ogni sito con il modello di scoring interno.
- Il sito finale e approvato dal Responsabile Operazioni Franchising.
- Tempistica tipica: 2-4 settimane per valutazione e approvazione.

## Specifiche di Allestimento
- Il layout del banco deve seguire lo standard Panino Bricks a 4 postazioni (Ordini, Preparazione, Cottura, Confezionamento/Consegna).
- Requisiti idraulici: acqua calda e fredda, scarico a pavimento, lavello a piu vasche, lavamani dedicato.
- Impianto elettrico: potenza adeguata al carico di piastra, forno, affettatrice e banco refrigerato.
- Ventilazione: cappa di aspirazione per la zona piastra/forno e HVAC adeguato.
- Interni: finiture standard Panino Bricks con grafiche brandizzate, illuminazione a sospensione e banconi su misura.
- Tempi di allestimento: 8-12 settimane dall'approvazione dei permessi.
"""),
        ("4. Formazione e Lancio", """
## Programma di Formazione Pre-Apertura
- 2 settimane presso una sede di formazione Panino Bricks (attualmente Milano Navigli).
- Copre preparazione di tutti i panini, sicurezza alimentare HACCP, servizio clienti, uso del POS, gestione scorte.
- Esame pratico obbligatorio: preparare tutti i 28 panini del menu a standard ed entro i tempi.
- Attestato di formazione alimentare richiesto per il titolare e tutto il personale prima dell'apertura.

## Selezione e Formazione del Personale
- Organico consigliato per una paninoteca standard: 6-8 operatori part-time, 1 responsabile di turno, 1 responsabile di sede.
- Panino Bricks fornisce i materiali formativi e un formatore in sede per le prime 2 settimane di attivita.
- Tutto il personale deve completare il programma del Manuale Operatore Panino Bricks.
- Moduli di aggiornamento rilasciati trimestralmente tramite il Portale Operazioni Panino Bricks.

## Protocollo di Grande Apertura
- Il team marketing fornisce il modello di campagna per la grande apertura.
- Promozione standard: "Grande Apertura" con offerte dedicate per le prime 2 settimane (come fatto per la recente apertura di Bolzano).
- Iniziative di PR locale e campagna sui social.
- Obiettivo: 2,5x il volume giornaliero normale durante il periodo di grande apertura.

## Riepilogo Tempistiche di Lancio
- Mese 1-2: firma del contratto di franchising, avvio selezione del sito.
- Mese 2-3: sito approvato, contratto di locazione firmato, permessi depositati.
- Mese 3-5: allestimento e installazione attrezzature.
- Mese 5: avvio selezione del personale.
- Mese 5-6: formazione del titolare presso la sede di formazione.
- Mese 6: formazione del personale, soft opening (amici e parenti).
- Mese 6-7: grande apertura.
"""),
    ],
)

manutenzione_attrezzature = (
    "Guida Manutenzione Attrezzature",
    [
        ("1. Panoramica delle Attrezzature", """
Ogni paninoteca Panino Bricks e dotata delle seguenti attrezzature standard. Una manutenzione corretta garantisce qualita costante dei panini, conformita alla sicurezza alimentare e lunga durata delle attrezzature.

## Elenco delle Attrezzature Principali
- Piastra professionale (1-2 per sede): per scaldare e schiacciare i panini "Caldo alla Piastra". Superficie liscia o rigata.
- Tostapane professionale (1-2 per sede): per la tostatura del pane. Temperatura regolabile.
- Affettatrice (1 per sede): per affettare salumi al momento (Mortadella IGP, Prosciutto Crudo, Salame Milano, Speck, Culatello). Lama di grande diametro.
- Forno (1 per sede): per gratinare formaggi (Mozzarella, scamorza) e scaldare le farciture.
- Banco refrigerato (1 per sede): conserva salumi, latticini e verdure pronti all'uso durante il servizio.
- Cella frigorifera (1 per sede): scorta refrigerata di salumi, latticini e ingredienti deperibili.
- Terminale POS e schermo ordini (1 per sede): gestione ordini, integrazione App Mobile e display ordini per il cliente.
"""),
        ("2. Procedure di Pulizia Quotidiana", """
Queste procedure vanno completate ogni giorno, tipicamente in chiusura.

## Piastra
- A fine servizio, raschia i residui dalla superficie con la spatola dedicata.
- Pulisci la piastra ancora tiepida con prodotto sgrassante alimentare.
- Verifica che la manopola di temperatura risponda correttamente.
- Settimanale: pulizia profonda della superficie e dei canali di scolo grassi.

## Tostapane
- Svuota il vassoio raccogli-briciole a fine giornata.
- Pulisci griglie e superfici interne da residui di pane.
- Verifica che le resistenze si scaldino in modo uniforme; pane non uniformemente tostato indica una resistenza da controllare.

## Affettatrice
- IMPORTANTE: spegni e scollega sempre l'affettatrice prima della pulizia.
- Smonta le parti a contatto (piatto, paralama) e sanificale dopo ogni giornata e tra salumi diversi quando richiesto.
- Pulisci la lama con un panno dal centro verso l'esterno, indossando guanti anti-taglio.
- Settimanale: verifica l'affilatura della lama; una lama poco affilata schiaccia il salume invece di affettarlo.

## Forno
- Pulisci l'interno da residui di formaggio e grassi a fine giornata.
- Verifica che la guarnizione dello sportello chiuda bene.
- Settimanale: pulizia profonda di ripiani e teglie.

## Banco Refrigerato e Cella
- Pulisci e sanifica ripiani e pareti settimanalmente.
- Controlla e registra le temperature due volte per turno (devono restare a 0-4 gradi C per il banco e la cella).
- Mensile: verifica le guarnizioni degli sportelli; sostituiscile se screpolate o lente.
- Trimestrale: pulisci le serpentine del condensatore (aspira la polvere) per mantenere l'efficienza.
"""),
        ("3. Piano di Manutenzione Preventiva", """
## Manutenzione Settimanale
- Verifica affilatura della lama dell'affettatrice.
- Controllo uniformita di riscaldamento di piastra e tostapane.
- Pulizia profonda dei canali grassi della piastra.
- Verifica dei termometri di banco refrigerato e cella contro un termometro di riferimento calibrato.

## Manutenzione Mensile
- Ispezione delle guarnizioni degli sportelli di banco refrigerato e cella.
- Controllo di cavi e spine elettriche per eventuali danni.
- Lubrificazione delle parti mobili dell'affettatrice secondo le indicazioni del produttore.
- Test del backup e della connettivita del sistema POS.
- Pulizia di ventole e prese d'aria.

## Manutenzione Trimestrale
- Pulizia delle serpentine del condensatore di banco refrigerato e cella.
- Ispezione del motore dell'affettatrice (rumori anomali, surriscaldamento).
- Verifica delle resistenze del forno e del tostapane.
- Audit completo delle attrezzature da parte del responsabile di sede con la Checklist Attrezzature Panino Bricks.

## Manutenzione Annuale
- Ispezione professionale di tutte le attrezzature principali.
- Calibrazione delle temperature di piastra, forno e tostapane.
- Affilatura professionale o sostituzione della lama dell'affettatrice.
- Revisione hardware e aggiornamento software del POS.
"""),
        ("4. Risoluzione dei Problemi Comuni", """
## Problemi della Piastra
- Problema: il panino non si scalda in modo uniforme.
  Soluzione: verifica che la piastra abbia raggiunto la temperatura di esercizio. Controlla la calibrazione della manopola; se la temperatura e errata, ricalibra o chiama l'assistenza.
- Problema: residui carbonizzati che attaccano il pane.
  Soluzione: esegui la pulizia profonda della superficie e dei canali grassi.

## Problemi del Tostapane
- Problema: pane tostato in modo irregolare.
  Soluzione: una resistenza non scalda uniformemente. Verifica le resistenze e sostituiscile se necessario.
- Problema: il pane si brucia.
  Soluzione: la temperatura e troppo alta o il timer e tarato male. Regola la temperatura e verifica il timer.

## Problemi dell'Affettatrice
- Problema: il salume si schiaccia invece di affettarsi.
  Soluzione: la lama e poco affilata. Procedi con l'affilatura o sostituisci la lama.
- Problema: l'affettatrice vibra o fa rumore.
  Soluzione: spegni e scollega. Controlla il fissaggio della lama e lo stato dei cuscinetti; se il rumore persiste, chiama l'assistenza.

## Problemi del Forno
- Problema: il formaggio non gratina.
  Soluzione: verifica che il forno raggiunga la temperatura. Controlla le resistenze e la guarnizione dello sportello.

## Problemi del Banco Refrigerato e della Cella
- Problema: temperatura sopra la soglia di sicurezza.
  Soluzione: controlla la guarnizione dello sportello e che chiuda completamente. Verifica che l'unita non sia sovraccarica (serve circolazione d'aria). Se il compressore gira di continuo senza raffreddare, chiama subito l'assistenza.
- Problema: eccessivo accumulo di brina.
  Soluzione: programma uno sbrinamento. Controlla la guarnizione ed evita di lasciare lo sportello aperto a lungo.

## Quando Chiamare l'Assistenza Professionale
- Qualsiasi problema elettrico (scintille, odore di bruciato, interruttori che scattano).
- Perdite di refrigerante (sibilo, unita che non raffredda nonostante il compressore in funzione).
- Danni strutturali alle attrezzature.
- Qualsiasi problema non risolto dai passaggi sopra.
- Tieni esposta in ufficio l'elenco dei contatti dei tecnici di manutenzione di ogni sede.
"""),
    ],
)

accordi_fornitori = (
    "Riepilogo Accordi Fornitori",
    [
        ("1. Elenco Fornitori", """
Panino Bricks mantiene accordi con 8 fornitori approvati. Tutti gli acquisti di ingredienti e materiali devono passare da questi fornitori autorizzati. Non sono ammessi acquisti da fornitori non autorizzati.

## SUP-001: Salumificio Emiliano S.r.l.
- Paese: Italia (Emilia-Romagna)
- Categoria: Salumi
- Prodotti forniti: Mortadella IGP, Prosciutto Crudo, Salame Milano, Speck Alto Adige, Culatello di Zibello
- Lead time: 4 giorni
- Affidabilita: 4.8/5.0
- Termini di pagamento: 30 giorni
- Contatto: ordini tramite portale B2B. Conferme entro 24 ore.

## SUP-002: Caseificio del Sud
- Paese: Italia (Sud Italia)
- Categoria: Formaggi & Latticini
- Prodotti forniti: Mozzarella Fiordilatte, Pecorino Romano, Stracciatella di Bufala, Burrata Pugliese
- Lead time: 2 giorni
- Affidabilita: 4.9/5.0
- Termini di pagamento: 7 giorni
- Minimo d'ordine: 100 EUR
- Contatto: consegna su rotta giornaliera. Ordini entro le 14:00 per consegna il giorno successivo.
- Nota: fornitore tra i piu affidabili. Critico per le operazioni quotidiane data la natura deperibile dei latticini.

## SUP-003: Forno Artigiano Milano
- Paese: Italia (Lombardia)
- Categoria: Pane & Focacce
- Prodotti forniti: Michette, Focaccia Genovese, Ciabatta, Pane ai Cereali, Pane Casereccio, Piadina
- Lead time: 1 giorno
- Affidabilita: 4.7/5.0
- Termini di pagamento: 15 giorni
- Minimo d'ordine: 80 EUR
- Contatto: consegna giornaliera del pane fresco. Ordini entro le 16:00 per la mattina successiva.
- Nota: lead time piu breve di tutti. Il pane e fresco di giornata e va consumato in giornata.

## SUP-004: Ortofrutta Fresca S.p.A.
- Paese: Italia
- Categoria: Verdure & Ortaggi
- Prodotti forniti: Friarielli, Rucola, Melanzane, Funghi Champignon, pomodori, basilico
- Lead time: 2 giorni
- Affidabilita: 4.4/5.0
- Termini di pagamento: 15 giorni
- Minimo d'ordine: 120 EUR
- Contatto: ordini tramite portale all'ingrosso.
- Nota: affidabilita piu bassa tra i fornitori. Mantenere una scorta cuscinetto di qualche giorno per le verdure.
"""),
        ("2. Elenco Fornitori (Continua)", """
## SUP-005: Tartufi & Specialita Alba
- Paese: Italia (Piemonte)
- Categoria: Specialita & Tartufi
- Prodotti forniti: Tartufo Nero, tartufo bianco d'Alba (stagionale), specialita
- Lead time: 6 giorni
- Affidabilita: 4.9/5.0
- Termini di pagamento: 30 giorni
- Minimo d'ordine: 500 EUR
- Contatto: ordini via email al team commerciale. Spedizioni con certificato di provenienza.
- Nota: lead time lungo e prodotto pregiato. Senza tartufo non sono disponibili Tartufo & Stracciatella, Tartufo Bianco d'Alba, ne la promo "Lunedi del Tartufo". Monitorare le scorte con attenzione.

## SUP-006: Salse & Condimenti Italia
- Paese: Italia
- Categoria: Salse & Condimenti
- Prodotti forniti: Maionese, Senape, Salsa Tartufata, Pesto Genovese
- Lead time: 3 giorni
- Affidabilita: 4.6/5.0
- Termini di pagamento: 15 giorni
- Minimo d'ordine: 100 EUR
- Contatto: portale di ordinazione online con opzione di consegna programmata.
- Nota: il Pesto Genovese contiene frutta a guscio (pinoli/anacardi); verificare l'etichetta a ogni lotto per la gestione allergeni.

## SUP-007: EcoPack Imballaggi
- Paese: Italia
- Categoria: Packaging
- Prodotti forniti: Carta Alimentare, sacchetti, tovaglioli, incarti per delivery
- Lead time: 7 giorni
- Affidabilita: 4.4/5.0
- Termini di pagamento: 30 giorni
- Minimo d'ordine: 250 EUR
- Contatto: si consigliano ordini ricorrenti quindicinali. Contattare il referente vendite per tirature personalizzate con il brand.

## SUP-008: Conserve Mediterranee
- Paese: Italia
- Categoria: Conserve & Ittico
- Prodotti forniti: Tonno sott'olio, baccala, conserve ittiche
- Lead time: 5 giorni
- Affidabilita: 4.5/5.0
- Termini di pagamento: 15 giorni
- Minimo d'ordine: 150 EUR
- Contatto: ordini via portale distributore.
- Nota: prodotti ittici, allergene pesce. Conservare le conserve in luogo fresco e asciutto fino all'apertura.
"""),
        ("3. Politiche di Riordino e Soglie di Inventario", """
## Trigger di Riordino Automatico
I responsabili di sede devono monitorare le scorte e ordinare al raggiungimento della soglia di riordino. Di seguito i punti di riordino per gli ingredienti chiave.

- Mortadella IGP: riordina sotto soglia. Ordina da SUP-001 (lead time 4 giorni).
- Prosciutto Crudo: riordina sotto soglia. Ordina da SUP-001 (lead time 4 giorni).
- Salame Milano e Speck Alto Adige: ordina da SUP-001 (lead time 4 giorni).
- Mozzarella Fiordilatte: riordina spesso (deperibile). Ordina da SUP-002 (lead time 2 giorni). Ordinare piu volte a settimana.
- Stracciatella di Bufala e Burrata Pugliese: deperibili, riordino frequente da SUP-002 (lead time 2 giorni).
- Pecorino Romano: ordina da SUP-002 (lead time 2 giorni).
- Pane (Michette, Focaccia, Ciabatta, ecc.): ordine giornaliero da SUP-003 (lead time 1 giorno). Consumare in giornata.
- Friarielli, Rucola, Melanzane, Funghi: ordina da SUP-004 (lead time 2 giorni), mantenendo scorta cuscinetto.
- Tartufo Nero: riordina con largo anticipo. Ordina da SUP-005 (lead time 6 giorni!).
- Maionese, Senape, Salsa Tartufata, Pesto Genovese: ordina da SUP-006 (lead time 3 giorni).
- Carta Alimentare e packaging: ordina da SUP-007 (lead time 7 giorni), con ordini ricorrenti quindicinali.
- Tonno sott'olio e baccala: ordina da SUP-008 (lead time 5 giorni).

## Consolidamento Ordini
- Consolida gli ordini verso lo stesso fornitore per raggiungere il minimo d'ordine e ridurre i costi di spedizione.
- I fornitori con lead time piu lungo (SUP-005 Tartufi, SUP-007 Packaging) vanno ordinati con anticipo sufficiente a coprire la variabilita dei tempi.
- I latticini (SUP-002) e il pane (SUP-003) vanno ordinati con grande frequenza data la deperibilita.

## Ordini di Emergenza
Se un ingrediente critico finisce inaspettatamente:
- Pane (SUP-003): consegna in giornata possibile contattando direttamente il forno al mattino presto.
- Latticini (SUP-002): possibile consegna prioritaria con piccolo sovrapprezzo; chiamare la linea dispatch.
- Salumi e specialita (SUP-001, SUP-005): nessuna opzione di emergenza rapida. Per questo le scorte cuscinetto su salumi e tartufo sono fondamentali.
"""),
        ("4. Termini Contrattuali e Monitoraggio delle Prestazioni", """
## Termini Contrattuali Standard
- Tutti gli accordi con i fornitori sono rivisti e rinnovati annualmente.
- I prezzi sono bloccati per 12 mesi dalla firma del contratto, con possibilita di adeguamento se i costi delle materie prime variano oltre il 15%.
- Standard di qualita definiti in ogni contratto: tutti gli ingredienti devono rispettare i requisiti di sicurezza alimentare e le specifiche di qualita Panino Bricks.
- Diritto di audit: Panino Bricks puo ispezionare gli stabilimenti dei fornitori con 30 giorni di preavviso.

## Metriche di Prestazione
Ogni fornitore e valutato trimestralmente su:
- Tasso di consegna puntuale (obiettivo: 95%+)
- Accuratezza dell'ordine (obiettivo: 99%+)
- Costanza della qualita (obiettivo: zero incidenti qualitativi per trimestre)
- Reattivita nella comunicazione (obiettivo: risposta entro 24 ore)

## Riepilogo Prestazioni Attuali dei Fornitori
- SUP-001 (Salumificio Emiliano): 4.8/5.0 - Qualita eccellente dei salumi, raramente 1 giorno di ritardo.
- SUP-002 (Caseificio del Sud): 4.9/5.0 - Tra i migliori. Consegna affidabile, partner critico per i latticini freschi.
- SUP-003 (Forno Artigiano Milano): 4.7/5.0 - Pane fresco di giornata consegnato puntualmente.
- SUP-004 (Ortofrutta Fresca): 4.4/5.0 - Punteggio piu basso. Consegne in ritardo in alcuni trimestri. Mantenere scorta cuscinetto.
- SUP-005 (Tartufi & Specialita Alba): 4.9/5.0 - Qualita premium, consegna costante nonostante il lead time lungo. Vale il prezzo.
- SUP-006 (Salse & Condimenti Italia): 4.6/5.0 - Buone prestazioni. Attenzione all'allergene frutta a guscio nel pesto.
- SUP-007 (EcoPack Imballaggi): 4.4/5.0 - Occasionali ritardi su articoli personalizzati. Standard puntuali.
- SUP-008 (Conserve Mediterranee): 4.5/5.0 - Prestazioni solide su tonno e conserve ittiche.

## Risoluzione delle Controversie
- Problemi di qualita: documenta con foto e segnala al fornitore entro 48 ore. Accredito o spedizione sostitutiva entro il lead time standard.
- Dispute sui prezzi: escala al Responsabile Acquisti Panino Bricks. I prezzi sono quelli da contratto.
- Inadempienze ripetute: dopo 2 trimestri consecutivi sotto gli obiettivi, Panino Bricks avvia una revisione del fornitore e puo cercare alternative.
"""),
    ],
)

# =============================================================================
# GENERATE AND UPLOAD
# =============================================================================

documents = [
    manuale_operatore,
    ricettario_panini,
    sicurezza_alimentare_haccp,
    guida_franchising,
    manutenzione_attrezzature,
    accordi_fornitori,
]

file_names = [
    "manuale_operatore.pdf",
    "ricettario_panini.pdf",
    "sicurezza_alimentare_haccp.pdf",
    "guida_franchising.pdf",
    "manutenzione_attrezzature.pdf",
    "accordi_fornitori.pdf",
]

print(f"\nGenerating {len(documents)} PDF documents...")

for fname, (title, sections) in zip(file_names, documents):
    pdf_bytes = create_pdf(title, sections)
    upload_path = f"{VOLUME_PATH}/{fname}"
    w.files.upload(upload_path, io.BytesIO(pdf_bytes), overwrite=True)
    size_kb = len(pdf_bytes) / 1024
    print(f"  Uploaded {fname} ({size_kb:.1f} KB)")

# =============================================================================
# VERIFICATION
# =============================================================================
print(f"\nVerifying uploaded files in {VOLUME_PATH}/...")
from databricks.sdk.service.files import ListDirectoryResponse

listed = list(w.files.list_directory_contents(VOLUME_PATH))
for f in listed:
    print(f"  {f.path} ({f.file_size:,} bytes)" if f.file_size else f"  {f.path}")

print(f"\nDone! {len(documents)} KA documents uploaded to {VOLUME_PATH}/")
