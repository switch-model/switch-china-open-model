"""
This module was prepared by Yaofeng "Desmond" Zhong in collaboration with Liqun Peng

This module is more flexible than 're_connected_strategy.py', since we allow a subset of 
battery to be co-located with renewable power plants (to be included in the constraint).
In this way, we allow addtional grid-connected and demand-side batteries to be included 
in the model. Each province can choose a mixed of these three battery deploymennt strategies.
"""


from pyomo.environ import *
import os, collections

dependencies = 'switch_model.generators.extensions.storage'

def define_components(mod):
    """
    Add constraints to batteries where their `gen_is_re_connect` attributes are set to True
    the charge of these betteries should not exceed the dispatched renewable energy 
    (at any time point)
    """
    mod.gen_is_re_connect = Param(mod.GENERATION_PROJECTS, within=Boolean, default=False)
    # Summarize battery storage charging
    def battery_rule(m, z, t):
        # Construct and cache a set for summation as needed
        if not hasattr(m, 'Battery_Storage_Central_Charge_Summation_dict'):
            m.Battery_Storage_Central_Charge_Summation_dict = collections.defaultdict(set)
            for g, t2 in m.STORAGE_GEN_TPS:
                # must be re-connect
                if m.gen_tech[g] == "Battery_Storage" and not m.gen_is_distributed[g] and m.gen_is_re_connect[g]:
                    # only add battery in central
                    z2 = m.gen_load_zone[g]
                    m.Battery_Storage_Central_Charge_Summation_dict[z2, t2].add(g)
        # Use pop to free memory
        relevant_projects = m.Battery_Storage_Central_Charge_Summation_dict.pop((z, t), {})
        return sum(m.ChargeStorage[g, t] for g in relevant_projects)
    mod.REBatteryCentralCharge = Expression(mod.LOAD_ZONES, mod.TIMEPOINTS, rule=battery_rule)   

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
        mod.ZONE_TIMEPOINTS,
        rule=lambda m, z, t:
            m.REBatteryCentralCharge[z, t] <= m.RenewableDispatchZone[z, t] 
    )


def load_inputs(mod, switch_data, inputs_dir):
    # which batteries are re-connected
    switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'generation_projects_info.csv'),
        auto_select=True,
        optional_params=['gen_is_re_connect'],
        index=mod.GENERATION_PROJECTS,
        param=(mod.gen_is_re_connect))