import logging
from datetime import date

import pytest

from rag.ingestion.service_public import SOURCE, parse_fiche

DC_NS = 'xmlns:dc="http://purl.org/dc/elements/1.1/"'


def make_fiche(body: str, fiche_id: str = "F1", extra_attrs: str = "") -> bytes:
    """Wrap body elements into a minimal <Publication> with realistic metadata."""
    id_attr = f'ID="{fiche_id}"' if fiche_id else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Publication {DC_NS} {id_attr} type="Fiche d'information conditionnée"
    spUrl="https://www.service-public.gouv.fr/particuliers/vosdroits/{fiche_id}" {extra_attrs}>
  <dc:title>Titre de la fiche</dc:title>
  <dc:subject>Logement, Fiscalité</dc:subject>
  <dc:description>Résumé de la fiche.</dc:description>
  <dc:date>modified 2025-05-09</dc:date>
  <FilDAriane>
    <Niveau ID="Particuliers">Accueil particuliers</Niveau>
    <Niveau ID="N19808">Logement</Niveau>
  </FilDAriane>
  <DossierPere ID="N1"><Titre>Dossier</Titre><Fiche ID="F2">Fiche voisine</Fiche></DossierPere>
  {body}
</Publication>""".encode()


def test_metadata_is_extracted() -> None:
    doc = parse_fiche(make_fiche("<Texte><Paragraphe>Contenu.</Paragraphe></Texte>"))

    assert doc.doc_id == "F1"
    assert doc.source == SOURCE
    assert doc.title == "Titre de la fiche"
    assert doc.url == "https://www.service-public.gouv.fr/particuliers/vosdroits/F1"
    assert doc.doc_type == "Fiche d'information conditionnée"
    assert doc.modified_at == date(2025, 5, 9)
    assert doc.breadcrumb == ["Accueil particuliers", "Logement"]
    assert doc.themes == ["Logement", "Fiscalité"]
    assert doc.description == "Résumé de la fiche."


def test_text_starts_with_title_and_skips_navigation() -> None:
    doc = parse_fiche(make_fiche("<Texte><Paragraphe>Contenu.</Paragraphe></Texte>"))

    assert doc.text == "# Titre de la fiche\n\nContenu."
    assert "Fiche voisine" not in doc.text


def test_inline_markup_is_flattened_and_whitespace_collapsed() -> None:
    body = """<Texte><Paragraphe>Depuis le 1<Exposant>er</Exposant>   janvier,
      voir le <LienInterne LienPublication="R1">PLU</LienInterne> et
      <MiseEnEvidence>payer <Valeur>10 €</Valeur></MiseEnEvidence>.</Paragraphe></Texte>"""

    doc = parse_fiche(make_fiche(body))

    assert doc.text.endswith("Depuis le 1er janvier, voir le PLU et payer 10 €.")


def test_sections_and_cases_become_nested_headings() -> None:
    body = """<Texte><Chapitre>
      <Titre><Paragraphe>Démarches</Paragraphe></Titre>
      <SousChapitre>
        <Titre><Paragraphe>Dépôt</Paragraphe></Titre>
        <BlocCas affichage="radio">
          <Cas>
            <Titre>
À Paris</Titre>
            <TitreRiche><Paragraphe>À Paris</Paragraphe></TitreRiche>
            <Paragraphe>Par voie dématérialisée.</Paragraphe>
          </Cas>
        </BlocCas>
      </SousChapitre>
    </Chapitre></Texte>"""

    doc = parse_fiche(make_fiche(body))

    assert doc.text.split("\n\n")[1:] == [
        "## Démarches",
        "### Dépôt",
        "#### Cas : À Paris",
        "Par voie dématérialisée.",
    ]


def test_heading_level_is_capped() -> None:
    nested = "<Paragraphe>Profond.</Paragraphe>"
    for depth in range(7):
        nested = f"<BlocCas><Cas><Titre>C{depth}</Titre>{nested}</Cas></BlocCas>"

    doc = parse_fiche(make_fiche(f"<Texte>{nested}</Texte>"))

    assert "###### Cas : C0" in doc.text
    assert "#######" not in doc.text


def test_situations_are_rendered_as_sections() -> None:
    body = """<ListeSituations affichage="onglet"><Situation>
      <Titre>Vous êtes locataire</Titre>
      <Texte><Chapitre><Titre><Paragraphe>Préavis</Paragraphe></Titre>
        <Paragraphe>Un mois.</Paragraphe></Chapitre></Texte>
    </Situation></ListeSituations>"""

    doc = parse_fiche(make_fiche(body))

    assert "## Vous êtes locataire\n\n### Préavis\n\nUn mois." in doc.text


def test_lists_bulleted_numbered_and_nested() -> None:
    body = """<Texte>
      <Liste type="puce">
        <Item><Paragraphe>Premier</Paragraphe>
          <Liste type="puce"><Item><Paragraphe>Sous-point</Paragraphe></Item></Liste>
        </Item>
        <Item><Paragraphe>Second</Paragraphe></Item>
      </Liste>
      <Liste type="numero">
        <Item><Paragraphe>Étape A</Paragraphe></Item>
        <Item><Paragraphe>Étape B</Paragraphe></Item>
      </Liste>
    </Texte>"""

    doc = parse_fiche(make_fiche(body))

    assert "- Premier\n  - Sous-point\n- Second" in doc.text
    assert "1. Étape A\n2. Étape B" in doc.text


def test_table_with_caption_header_and_list_cell() -> None:
    body = """<Texte><Tableau>
      <TitreRiche><Paragraphe>Plafonds</Paragraphe></TitreRiche>
      <Colonne largeur="20" type="normal"/>
      <Rangée type="header">
        <Cellule><Paragraphe>Personnes</Paragraphe></Cellule>
        <Cellule><Paragraphe>Revenu</Paragraphe></Cellule>
      </Rangée>
      <Rangée type="normal">
        <Cellule><Paragraphe>1 personne</Paragraphe></Cellule>
        <Cellule><Paragraphe><Valeur>34 233 €</Valeur></Paragraphe></Cellule>
      </Rangée>
      <Rangée type="normal">
        <Cellule><Liste type="puce"><Item><Paragraphe>a</Paragraphe></Item>
          <Item><Paragraphe>b|c</Paragraphe></Item></Liste></Cellule>
      </Rangée>
    </Tableau></Texte>"""

    doc = parse_fiche(make_fiche(body))

    assert (
        "**Plafonds**\n\n"
        "| Personnes | Revenu |\n"
        "| --- | --- |\n"
        "| 1 personne | 34 233 € |\n"
        "| a ; b\\|c |  |"
    ) in doc.text


def test_callout_is_rendered_as_blockquote() -> None:
    body = """<Texte><ASavoir><Titre>À savoir</Titre>
      <Paragraphe>Point important.</Paragraphe>
      <Liste type="puce"><Item><Paragraphe>Détail</Paragraphe></Item></Liste>
    </ASavoir></Texte>"""

    doc = parse_fiche(make_fiche(body))

    assert "> **À savoir**\n>\n> Point important.\n>\n> - Détail" in doc.text


def test_where_to_go_and_online_service_keep_only_their_title() -> None:
    body = """<Texte>
      <OuSAdresser ID="R1"><Titre>Mairie</Titre><PivotLocal>mairie</PivotLocal></OuSAdresser>
      <ServiceEnLigne ID="R2" type="Téléservice"><Titre>Demande en ligne</Titre>
        <Source ID="S1">Ministère</Source></ServiceEnLigne>
    </Texte>"""

    doc = parse_fiche(make_fiche(body))

    assert "Où s'adresser : Mairie\n\nService en ligne : Demande en ligne" in doc.text
    assert "mairie" not in doc.text.replace("Mairie", "")
    assert "Ministère" not in doc.text


def test_questionnaire_conditions_and_media_are_skipped() -> None:
    body = """<Texte>
      <FragmentConditionne><Condition><estVrai var="T1"/></Condition>
        <Paragraphe>Texte conditionné.</Paragraphe></FragmentConditionne>
      <Video><Titre>Vidéo</Titre><Description>Description vidéo</Description></Video>
    </Texte>"""

    doc = parse_fiche(make_fiche(body))

    assert doc.text == "# Titre de la fiche\n\nTexte conditionné."


def test_unknown_block_keeps_text_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    body = "<Texte><NouvelleBalise><Paragraphe>Texte nouveau.</Paragraphe></NouvelleBalise></Texte>"

    with caplog.at_level(logging.WARNING):
        doc = parse_fiche(make_fiche(body))

    assert doc.text.endswith("Texte nouveau.")
    assert "NouvelleBalise" in caplog.text


def test_unknown_top_level_element_warns_but_is_not_rendered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = "<NouveauBloc>Hors corps.</NouveauBloc><Texte><Paragraphe>Corps.</Paragraphe></Texte>"

    with caplog.at_level(logging.WARNING):
        doc = parse_fiche(make_fiche(body))

    assert "Hors corps" not in doc.text
    assert "NouveauBloc" in caplog.text


def test_missing_optional_metadata_gives_none() -> None:
    xml = b'<Publication ID="F9"><Texte><Paragraphe>Seul.</Paragraphe></Texte></Publication>'

    doc = parse_fiche(xml)

    assert doc.modified_at is None
    assert doc.description is None
    assert doc.url is None
    assert doc.themes == []


def test_missing_id_raises() -> None:
    with pytest.raises(ValueError, match="no ID"):
        parse_fiche(make_fiche("<Texte/>", fiche_id=""))
