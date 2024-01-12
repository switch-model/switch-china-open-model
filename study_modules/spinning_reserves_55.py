import pyomo.environ as po

# custom spinning reserve rule, based on nrel_3_5_spinning_reserve_requirements()
# in the spinning_reserve module, but with 5% of load instead of 3% of load


def define_components(m):
    spinning_reserve_requirements(m)


def spinning_reserve_requirements(m):
    """
    SpinningReserveRequirement55[(b,t) in BALANCING_AREA_TIMEPOINTS] is an
    expression for upward and downward spinning reserve requirements of 5% of
    load plus 5% of renewable output. This is based on a heuristic described in
    NREL's 2010 Western Wind and Solar Integration study, but adding 5% to loads
    instead of 3% (to be a little more like a planning reserve margin). It is
    added to the Spinning_Reserve_Up_Requirements and
    Spinning_Reserve_Down_Requirements lists. If the local_td module is
    available with DER accounting, load will be set to WithdrawFromCentralGrid.
    Otherwise load will be set to lz_demand_mw.
    """

    def SpinningReserveRequirement55_rule(m, b, t):
        try:
            load = m.WithdrawFromCentralGrid
        except AttributeError:
            load = m.lz_demand_mw
        return 0.05 * sum(
            load[z, t] for z in m.LOAD_ZONES if b == m.zone_balancing_area[z]
        ) + 0.05 * sum(
            m.DispatchGen[g, t]
            for g in m.VARIABLE_GENS
            if (g, t) in m.VARIABLE_GEN_TPS
            and b == m.zone_balancing_area[m.gen_load_zone[g]]
        )

    m.SpinningReserveRequirement55 = po.Expression(
        m.BALANCING_AREA_TIMEPOINTS, rule=SpinningReserveRequirement55_rule
    )
    m.Spinning_Reserve_Up_Requirements.append("SpinningReserveRequirement55")
    m.Spinning_Reserve_Down_Requirements.append("SpinningReserveRequirement55")
