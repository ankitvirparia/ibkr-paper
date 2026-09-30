"""Strategy registry. To deploy a new strategy: add its file here."""
from .intraday_orb import IntradayORB
from .options_income import OptionsIncome
from .us_momentum import USEquityMomentum

STRATEGIES = {
    "us_momentum": USEquityMomentum,
    "options_income": OptionsIncome,
    "intraday_orb": IntradayORB,
}
