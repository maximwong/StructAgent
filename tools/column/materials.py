"""Versioned column-owned design strengths and Appendix A four-bar areas."""

MATERIAL_TABLE_VERSION = "gb-column-materials-2024-v1"
CONCRETE_FC_MPA = {"C25": "11.9", "C30": "14.3", "C35": "16.7", "C40": "19.1"}
LONGITUDINAL_FY_COMPRESSION_MPA = {"HRB400": "360"}
TIE_FY_MPA = {"HPB300": "270"}
FOUR_BAR_AREA_MM2 = {12: 452, 14: 615, 16: 804, 18: 1017,
                     20: 1256, 22: 1520, 25: 1964, 28: 2463}
CANDIDATE_DIAMETERS_MM = tuple(FOUR_BAR_AREA_MM2)
PHI_TABLE = ((8, "1"), (10, ".98"), (12, ".95"), (14, ".92"),
             (16, ".87"), (18, ".81"), (20, ".75"), (22, ".70"),
             (24, ".65"), (26, ".60"), (28, ".56"), (30, ".52"),
             (32, ".48"), (34, ".44"), (36, ".40"), (38, ".36"),
             (40, ".32"), (42, ".29"), (44, ".26"), (46, ".23"),
             (48, ".21"), (50, ".19"))
