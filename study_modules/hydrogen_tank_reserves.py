import os
from pyomo.environ import *


def define_components(m):
    # how often does this timeseries occur? If it happens less often, that means
    # each incident makes up more of the year when it does occur, so we need more
    # hydrogen in storage to be ready for it.
    m.ts_years_between_occurrence = Param(
        m.TIMESERIES, within=NonNegativeReals, default=1
    )

    # there must be enough storage to hold _all_ the production each period (net
    # of same-day consumption) note: this assumes we cycle the system only once
    # per year (store all energy, then release all energy)

    # this version is identical to Max_Store_Liquid_Hydrogen in hydrogen_supply,
    # except it multiplies consumption on tough-to-serve days to reflect the
    # fact that they may only occur once every n years but then require n times
    # as much hydrogen in that year as their weighting indicates
    m.Max_Store_Liquid_Hydrogen_with_Reserves = Constraint(
        m.LOAD_ZONES,
        m.PERIODS,
        rule=lambda m, z, p: sum(
            m.StoreLiquidHydrogenKg[z, ts]
            * m.ts_years_between_occurrence[ts]
            * m.ts_scale_to_year[ts]
            for ts in m.TS_IN_PERIOD[p]
        )
        <= m.LiquidHydrogenTankCapacityKg[z, p],
    )


def load_inputs(m, switch_data, inputs_dir):
    """
    Import hydrogen data from a .csv file.
    """
    switch_data.load_aug(
        filename=os.path.join(inputs_dir, "hydrogen_tank_reserve_days.csv"),
        param=(m.ts_years_between_occurrence),
    )
