"""
This module was prepared by Yaofeng "Desmond" Zhong in collaboration with Liqun Peng

This module adds constraints that for a set of load zones, total battery charge 
does not exceed total dispatched renewable energy (at any time point), representing 
batteries co-located with renewable power plants. The set of load zones where this 
constraint is effective can be specified using the boolean 'zone_is_constrained' 
column in 'load_zone.csv'.
"""

from pyomo.environ import *
import os, collections

dependencies = 'switch_model.generators.extensions.storage'

def define_components(mod):
    """
    Add constraints to let battery charge not exceed total dispatched renewable energy
    (at any time point)
    """
    # Set of specifying which load zone to constraint
    mod.zone_is_constrained = Param(mod.LOAD_ZONES, within=Boolean, default=False)
    mod.CONSTRAINED_ZONE_TIMEPOINTS = Set(
        initialize=mod.ZONE_TIMEPOINTS,
        filter=lambda m, z, tp: m.zone_is_constrained[z],
        doc="only include those zones which should be constrained")
    # Summarize battery storage charging
    def battery_rule(m, z, t):
        # Construct and cache a set for summation as needed
        if not hasattr(m, 'Battery_Storage_Central_Charge_Summation_dict'):
            m.Battery_Storage_Central_Charge_Summation_dict = collections.defaultdict(set)
            for g, t2 in m.STORAGE_GEN_TPS:
                if m.gen_tech[g] == "Battery_Storage" and not m.gen_is_distributed[g]:
                    # only add battery in central
                    z2 = m.gen_load_zone[g]
                    m.Battery_Storage_Central_Charge_Summation_dict[z2, t2].add(g)
        # Use pop to free memory
        relevant_projects = m.Battery_Storage_Central_Charge_Summation_dict.pop((z, t), {})
        return sum(m.ChargeStorage[g, t] for g in relevant_projects)
    mod.BatteryCentralCharge = Expression(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=battery_rule)   

    mod.Renewable_GEN_TPS = Set(
        dimen=2,
        initialize=lambda m: (
            (g, tp)
                for g in m.VARIABLE_GENS
                    for tp in m.TPS_FOR_GEN[g]))

    def rule(m, z, t):
        if not hasattr(m, 'Renewable_Gen_Summation_dict'):
            m.Renewable_Gen_Summation_dict = collections.defaultdict(set)
            for g, t2 in m.Renewable_GEN_TPS:
                z2 = m.gen_load_zone[g]
                m.Renewable_Gen_Summation_dict[z2, t2].add(g)
        # Use pop to free memory
        relevant_projects = m.Renewable_Gen_Summation_dict.pop((z, t), {})
        return sum(m.DispatchGen[g, t] for g in relevant_projects)
    mod.RenewableDispatchZone = Expression(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=rule)

    mod.Charge_Storage_Upper_Limit_Zone = Constraint(
        mod.CONSTRAINED_ZONE_TIMEPOINTS,
        rule=lambda m, z, t:
            m.BatteryCentralCharge[z, t] <= m.RenewableDispatchZone[z, t] 
    )


def load_inputs(mod, switch_data, inputs_dir):
    # which load zone should be constrainted
    switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'load_zones.csv'),
        auto_select=True,
        optional_params=['zone_is_constrained'],
        index=mod.LOAD_ZONES,
        param=(mod.zone_is_constrained))