"""Nationsspezifische Namenslisten für den Fahrergenerator (Abschnitt 5.3).

Alle Fahrer sind fiktiv. Die Listen enthalten gebräuchliche Vor- und
Nachnamen; Übereinstimmungen mit realen Personen sind Zufall.
"""

from __future__ import annotations

NATIONS: dict[str, str] = {
    "GER": "Deutschland",
    "AUT": "Österreich",
    "SUI": "Schweiz",
    "ITA": "Italien",
    "FRA": "Frankreich",
    "ESP": "Spanien",
    "GBR": "Großbritannien",
    "NED": "Niederlande",
    "BEL": "Belgien",
    "DEN": "Dänemark",
    "POL": "Polen",
    "USA": "Vereinigte Staaten",
}

#: Relative Häufigkeit im Fahrerpool.
NATION_WEIGHTS: dict[str, float] = {
    "GER": 3.0,
    "AUT": 1.4,
    "SUI": 1.2,
    "ITA": 2.0,
    "FRA": 2.0,
    "ESP": 1.6,
    "GBR": 1.6,
    "NED": 1.5,
    "BEL": 1.4,
    "DEN": 1.0,
    "POL": 1.0,
    "USA": 1.3,
}

FIRST_NAMES: dict[str, tuple[str, ...]] = {
    "GER": ("Jonas", "Lukas", "Felix", "Moritz", "Tobias", "Niklas", "Sebastian", "Jannik",
            "Maximilian", "Florian", "Simon", "Hendrik", "Kilian", "Marvin", "Ole", "Bastian"),
    "AUT": ("Matthias", "Stefan", "Georg", "Andreas", "Lukas", "Fabian", "Christoph", "Bernhard",
            "Elias", "Valentin", "Gregor", "Hannes", "Raphael", "Tobias", "Klemens", "Severin"),
    "SUI": ("Silvan", "Marco", "Reto", "Fabian", "Nico", "Cyrill", "Andri", "Gian",
            "Lars", "Robin", "Simon", "Yannick", "Kevin", "Joel", "Timon", "Beat"),
    "ITA": ("Matteo", "Lorenzo", "Alessandro", "Davide", "Andrea", "Giulio", "Federico", "Simone",
            "Marco", "Nicola", "Riccardo", "Tommaso", "Filippo", "Emanuele", "Stefano", "Luca"),
    "FRA": ("Julien", "Thibaut", "Romain", "Antoine", "Baptiste", "Clément", "Guillaume", "Maxime",
            "Rémi", "Florian", "Quentin", "Valentin", "Arnaud", "Hugo", "Mathis", "Corentin"),
    "ESP": ("Javier", "Álvaro", "Sergio", "Iván", "Rubén", "Jorge", "Carlos", "Miguel",
            "Adrián", "Óscar", "Marcos", "Pablo", "Unai", "Iker", "Gonzalo", "Aitor"),
    "GBR": ("Oliver", "Harry", "George", "Callum", "Tom", "Alfie", "Ewan", "Rhys",
            "Connor", "Dan", "Josh", "Freddie", "Lewis", "Owen", "Charlie", "Nathan"),
    "NED": ("Sven", "Bram", "Daan", "Jelle", "Thijs", "Wouter", "Ruben", "Koen",
            "Stijn", "Lars", "Joris", "Sander", "Bas", "Teun", "Rick", "Maarten"),
    "BEL": ("Wout", "Jasper", "Tim", "Robbe", "Senne", "Arne", "Lander", "Dries",
            "Nils", "Ward", "Milan", "Seppe", "Brent", "Jarne", "Kobe", "Vincent"),
    "DEN": ("Mads", "Kasper", "Jonas", "Emil", "Rasmus", "Anders", "Frederik", "Magnus",
            "Nikolaj", "Søren", "Oliver", "Mikkel", "Jeppe", "Villads", "Asger", "Lasse"),
    "POL": ("Kacper", "Bartosz", "Michał", "Tomasz", "Paweł", "Jakub", "Mateusz", "Piotr",
            "Rafał", "Krzysztof", "Adam", "Szymon", "Filip", "Marcin", "Wojciech", "Damian"),
    "USA": ("Tyler", "Brandon", "Jared", "Cole", "Austin", "Evan", "Derek", "Casey",
            "Trevor", "Shane", "Devin", "Garrett", "Blake", "Chase", "Logan", "Curtis"),
}

LAST_NAMES: dict[str, tuple[str, ...]] = {
    "GER": ("Brandt", "Vogler", "Kaltenbach", "Heinrich", "Ostermann", "Reinhardt", "Sturm",
            "Wiegand", "Falkenberg", "Merten", "Sandner", "Rothbauer", "Kienzle", "Nolte",
            "Ebersbach", "Hufnagel"),
    "AUT": ("Steinlechner", "Gruber", "Hofstätter", "Aigner", "Pichler", "Ranzinger", "Moosbrugger",
            "Zeilinger", "Haslinger", "Kirchmair", "Eibl", "Wieser", "Prantl", "Sailer",
            "Aichinger", "Rebernig"),
    "SUI": ("Brunner", "Zurbriggen", "Frei", "Aebersold", "Rüegg", "Cadonau", "Bättig",
            "Schneiter", "Hodel", "Vonlanthen", "Bernasconi", "Lauber", "Marti", "Gasser",
            "Studer", "Amrein"),
    "ITA": ("Bellandi", "Carraro", "Fontanelli", "Moretti", "Sartori", "Vigano", "Ferrero",
            "Zanotti", "Pastore", "Rinaldi", "Tosetti", "Basso", "Colombari", "Mazzocchi",
            "Perotti", "Salvadori"),
    "FRA": ("Lemoine", "Barrault", "Vidal", "Chapuis", "Delahaye", "Fournier", "Marchand",
            "Roussel", "Gauthier", "Perrin", "Aubert", "Lacroix", "Mercier", "Thibault",
            "Bouchard", "Vasseur"),
    "ESP": ("Aranda", "Bermúdez", "Cabrera", "Elizalde", "Gallardo", "Herrero", "Izaguirre",
            "Larrea", "Mendoza", "Otero", "Quintana", "Rivas", "Sedano", "Ugarte",
            "Valcárcel", "Zubiría"),
    "GBR": ("Ashworth", "Brookes", "Chatterton", "Dunmore", "Eastwood", "Fairhurst", "Grantham",
            "Hollis", "Kingsley", "Lansdale", "Mowbray", "Prescott", "Radcliffe", "Stanbury",
            "Thorne", "Waverley"),
    "NED": ("Boersma", "De Ruiter", "Van Dijk", "Hoekstra", "Kamphuis", "Leeuwen", "Mulder",
            "Nijhoff", "Oosterhuis", "Prins", "Roelofs", "Steenbergen", "Terlouw", "Vermeer",
            "Wagenaar", "Zwart"),
    "BEL": ("Aerts", "Beeckman", "Cools", "Dewulf", "Everaert", "Goossens", "Hendrickx",
            "Janssens", "Lambrecht", "Maes", "Nys", "Peeters", "Roelandts", "Segers",
            "Vandaele", "Wauters"),
    "DEN": ("Aagaard", "Bjerre", "Dahlgaard", "Enevoldsen", "Fogh", "Gundersen", "Hvid",
            "Jessen", "Kjeldsen", "Lundgren", "Mogensen", "Nørgaard", "Overgaard", "Riis",
            "Skovgaard", "Thybo"),
    "POL": ("Adamczyk", "Bielecki", "Chmielewski", "Dąbrowski", "Grabowski", "Jasiński",
            "Kowalczyk", "Lewandowski", "Malinowski", "Nowicki", "Pawlak", "Rutkowski",
            "Sikora", "Urbaniak", "Wójcik", "Zieliński"),
    "USA": ("Alderman", "Bridgewater", "Coleridge", "Dunlap", "Ellery", "Fairbanks", "Granger",
            "Halloway", "Ivers", "Jennings", "Kessler", "Lockhart", "Marlowe", "Northrup",
            "Pemberton", "Quimby"),
}

#: Bausteine für Teamnamen – ergeben zusammen plausible Ultra-Teams.
TEAM_PREFIXES = (
    "Nordwind", "Alpenrand", "Meridian", "Kettenreaktion", "Polarstern", "Hinterland",
    "Rückenwind", "Weitwinkel", "Kilometerfresser", "Tagwerk", "Nachtschicht", "Fernblick",
    "Steilhang", "Bergstation", "Windkanal", "Dauerlauf", "Randonneur", "Grenzgänger",
    "Höhenmeter", "Talsohle", "Kurbelwelle", "Sonnenaufgang", "Schotterpiste", "Wegweiser",
    "Zeitfenster", "Trittfrequenz", "Ausreißer", "Schlafmütze", "Vollgas", "Rollentiefe",
    "Sattelfest", "Marathon", "Tempomacher", "Kompass", "Nebelbank",
)

TEAM_SUFFIXES = (
    "Racing", "Ultra", "Endurance", "Cycling", "Collective", "Project", "Squad",
    "Team", "Crew", "Werkstatt",
)
