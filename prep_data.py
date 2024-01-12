# %% setup
import os, glob, shutil, subprocess, tempfile
import pandas as pd


def mkdir(dest):
    print(f"creating {dest}")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.mkdir(dest)


def copydir(src, dest):
    # copy specified directory and also report that the new directory
    # is being created
    print(f"creating {dest}")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


###################
# Copy base directory to "_start" one, then make some basic changes there.
copydir("inputs", "inputs_start")

# Turn off gen_min_build_capacity to avoid creating integer variables that slow
# the solver (a lot). This feature is not needed for this study and generally
# not needed in large power systems.
gi = pd.read_csv("inputs_start/gen_info.csv", na_values=".")
gi.loc[:, "gen_min_build_capacity"] = float("nan")
gi.to_csv("inputs_start/gen_info.csv", na_rep=".", index=False)

# generate alternative carbon cap and cost files
cp = pd.read_csv("inputs_start/carbon_policies.csv", na_values=".").set_index(
    "PERIOD", drop=False
)
cp.loc[2033:2048, "carbon_cap_tco2_per_yr"] = float("nan")
carbon_caps = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 40, 50, 60, 80, 100, 150, 200]
# interpolate from 2028 to 2048, which will be a percentage of 2048
for cap in carbon_caps:
    cpn = cp.copy()
    # set final cap
    cpn.loc[2048, "carbon_cap_tco2_per_yr"] = (
        cap * 0.01 * cpn.loc[2028, "carbon_cap_tco2_per_yr"]
    )
    # interpolate up to final level
    cpn.interpolate(method="index", inplace=True)
    cpn.to_csv(f"inputs_start/carbon_policies_{cap:03d}.csv", na_rep=".", index=False)

# make a carbon price that rises linearly from $0 in 2028 to $200 in 2048
cpn = cp.copy()
cpn.loc[2033:, "carbon_cost_dollar_per_tco2"] = float("nan")
cpn.loc[2048, "carbon_cost_dollar_per_tco2"] = 200
cpn.interpolate(method="index", inplace=True)
cpn.loc[:, "carbon_cap_tco2_per_yr"] = float("nan")
cpn.to_csv(f"inputs_start/carbon_policies_price_200.csv", na_rep=".", index=False)

# add prerelease version of hawaii_save_results to modules.txt to produce some
# extra outputs for this study (may just be energy_sources_{scen}.csv which is
# used to find expensive days and the summary_{scen}.csv file, which is used by
# analyze_results.py because it shows LCOE correctly)
with open("inputs_start/modules.txt") as f:
    text = f.read()
if not text.endswith("\n"):
    text += "\n"
text += "study_modules.hawaii_save_results\n"
with open("inputs_start/modules.txt", "w") as f:
    f.write(text)

###################
# Copy inputs_start to inputs_updated, then make various changes there
copydir("inputs_start", "inputs_updated")

###################
# switch to more realistic interest and discount rates
# see https://www.irena.org/Publications/2023/May/The-cost-of-financing-for-renewable-power

fin = pd.read_csv("inputs_updated/financials.csv", na_values=".")
fin["interest_rate"] = 0.04
fin["discount_rate"] = 0.03
fin.to_csv("inputs_updated/financials.csv", na_rep=".", index=False)

# %%########################
# Convert Switch-China costs to 2022 dollars and use NREL ATB costs and lifetime
# for solar, wind and storage

# convert ATB prices (2021$) to base year for this model (2022)
# https://fred.stlouisfed.org/series/GDPDEF#0
atb_deflator = 127.215 / 118.866

# convert Switch-China prices (2010$) to base year for this model (2022)
switch_china_deflator = 127.215 / 96.162

fin = pd.read_csv("inputs_updated/financials.csv", na_values=".")
fin[
    "base_financial_year"
] = 2022  # shouldn't affect LCOE or $/tonne calculations, but good to be consistent with other terms

bc = pd.read_csv("inputs_updated/gen_build_costs.csv", na_values=".")
gi = pd.read_csv("inputs_updated/gen_info.csv", na_values=".")
gt = gi[["GENERATION_PROJECT", "gen_tech"]]

# lookup gen tech
bc = bc.merge(gt, how="left")

# convert Switch-China data to 2022 dollars
bc.loc[
    :, ["gen_overnight_cost", "gen_fixed_om", "gen_storage_energy_overnight_cost"]
] *= switch_china_deflator
gi.loc[:, ["gen_variable_om", "gen_connect_cost_per_mw"]] *= switch_china_deflator

# Apply prices for solar and storage from NREL ATB 2023
# (Research/Switch/Switch-Hawaii/data/Generator Info/PSIP 2016-12 ATB 2023 generator data.xlsx)

tech = pd.DataFrame(
    [
        ("Central_PV", "CentralTrackingPV"),
        ("Commercial_PV", "FlatDistPV"),
        ("Residential_PV", "SlopedDistPV"),
        ("Wind", "OnshoreWind"),
        ("Offshore_Wind", "OffshoreWind"),
        ("Battery_Storage", "Battery_Bulk"),
    ],
    columns=["gen_tech", "Technology"],
)

ccmw = (
    pd.read_excel("ATB 2023 costs.xlsx", sheet_name="Capital Cost kW")
    .merge(tech)
    .set_index("gen_tech")
    .loc[:, 2021:2050]
    .stack()
)

ccmwh = (
    pd.read_excel("ATB 2023 costs.xlsx", sheet_name="Capital Cost kWh")
    .merge(tech)
    .set_index("gen_tech")
    .loc[:, 2021:2050]
    .stack()
)

fom = (
    pd.read_excel("ATB 2023 costs.xlsx", sheet_name="Fixed O&M")
    .merge(tech)
    .set_index("gen_tech")
    .loc[:, 2021:2050]
    .stack()
)

new_bc = (
    pd.DataFrame(
        {
            "gen_overnight_cost": ccmw,
            "gen_fixed_om": fom,
            "gen_storage_energy_overnight_cost": ccmwh,
        }
    )
    * 1000
    * atb_deflator
)
new_bc.index.names = ["gen_tech", "build_year"]

bc = bc.set_index(["gen_tech", "build_year"])
# note: if we use .round() before updating (whether or not we convert to int),
# we get a warning below that in the future pandas will try to update the
# columns in bc in place (since they are ints). So we don't bother to round, and
# then pandas recognizes it must create a float column and doesn't complain.
bc.update(new_bc)
bc = (
    bc.reset_index()
    .drop("gen_tech", axis=1)
    .set_index(["GENERATION_PROJECT", "build_year"])
    .reset_index()
)

bc.to_csv("inputs_updated/gen_build_costs.csv", na_rep=".", index=False)

# use ATB project life (30 years) and variable O&M ($0) for these technologies
# see https://atb.nrel.gov/electricity/2022/definitions#costrecoveryperiod
# and https://www.dropbox.com/scl/fi/b601904u6qqlxgku3ru5x/PSIP-2016-12-ATB-2023-generator-data.xlsx?rlkey=s2v8h799ewaars1cu6j3wht53&dl=0
# note: this assumes battery refurbishment at 10 and 20 years is included in fixed O&M
atb_sources = ["Storage", "Solar", "Wind"]  # from gi['gen_energy_source'].unique()
gi.loc[gi["gen_energy_source"].isin(atb_sources), "gen_max_age"] = 30
gi.loc[gi["gen_energy_source"].isin(atb_sources), "gen_variable_om"] = 0.0
gi.to_csv("inputs_updated/gen_info.csv", na_rep=".", index=False)

############
# Allow suspension (early/temporary retirement)
# first save a version of the module list without for use in diagnostics later.
shutil.copy2("inputs_updated/modules.txt", "inputs_updated/modules.no_suspend.txt")
with open("inputs_updated/modules.txt") as f:
    lines = f.readlines()
if not lines[-1].endswith("\n"):
    lines[-1] += "\n"
# swap out the gen build module
lines[
    lines.index("switch_model.generators.core.build\n")
] = "study_modules.gen_build_suspend\n"
with open("inputs_updated/modules.txt", "w") as f:
    f.writelines(lines)

#############
# Save a version of the generator files with all the updates except CCS or H2,
# for use in diagnostics later.
shutil.copy2("inputs_updated/gen_info.csv", "inputs_updated/gen_info.no_ccs_h2.csv")
shutil.copy2(
    "inputs_updated/gen_build_costs.csv", "inputs_updated/gen_build_costs.no_ccs_h2.csv"
)
shutil.copy2("inputs_updated/modules.txt", "inputs_updated/modules.no_ccs_h2.txt")


# %%###############
# Add hydrogen fuel cells and hydrogen and CCS retrofits
###############


#############################
# Create hydrogen.csv
# (based on code in https://github.com/switch-hawaii/ulupono_scenario_2.1/blob/master/get_scenario_data.py)

# electrolyzer data from centralized current electrolyzer scenario version 3.1 in
# http://www.hydrogen.energy.gov/h2a_prod_studies.html ->
# "Current Central Hydrogen Production from PEM Electrolysis version 3.101.xlsm"
# and
# "Future Central Hydrogen Production from PEM Electrolysis version 3.101.xlsm" (2025)
# (cited by 46719.pdf)
# note: we neglect land costs because they are small and can be recovered later
# TODO: move electrolyzer refurbishment costs from fixed to variable

# liquefier and tank data from http://www.nrel.gov/docs/fy99osti/25106.pdf

# fuel cell data from http://www.nrel.gov/docs/fy10osti/46719.pdf

# note: the article below shows 44% efficiency converting electricity to liquid
# fuels, then 30% efficiency converting to traction (would be similar for electricity),
# so power -> liquid fuel -> power would probably be less efficient than
# power -> hydrogen -> power. On the other hand, it would avoid the fuel cell
# investments and/or could be used to make fuel for air/sea freight, so may be
# worth considering eventually. (solar at $1/W with 28% cf would cost
# https://www.greencarreports.com/news/1113175_electric-cars-win-on-energy-efficiency-vs-hydrogen-gasoline-diesel-analysis
# https://twitter.com/lithiumpowerlpi/status/911003718891454464

# inflators from https://fred.stlouisfed.org/series/GDPDEF#0, with 2010 as base year for Switch-China
inflate_1995 = 96.162 / 71.820
inflate_2007 = 96.162 / 92.638
inflate_2008 = 96.162 / 94.423
h2_lhv_mj_per_kg = (
    120.21  # from http://hydrogen.pnl.gov/tools/lower-and-higher-heating-values-fuels
)
h2_mwh_per_kg = h2_lhv_mj_per_kg / 3600  # (3600 MJ/MWh)

current_electrolyzer_kg_per_mwh = (
    1000.0 / 54.3
)  # (1000 kWh/1 MWh)(1kg/54.3 kWh)   # TMP_Usage
current_electrolyzer_mw = (
    50000.0 * (1.0 / current_electrolyzer_kg_per_mwh) * (1.0 / 24.0)
)  # (kg/day) * (MWh/kg) * (day/h)    # design_cap cell
future_electrolyzer_kg_per_mwh = 1000.0 / 50.2  # TMP_Usage cell
future_electrolyzer_mw = (
    50000.0 * (1.0 / future_electrolyzer_kg_per_mwh) * (1.0 / 24.0)
)  # (kg/day) * (MWh/kg) * (day/h)    # design_cap cell

current_hydrogen_info = dict(
    hydrogen_electrolyzer_capital_cost_per_mw=144641663
    * inflate_2007
    / current_electrolyzer_mw,  # depr_cap cell
    hydrogen_electrolyzer_fixed_cost_per_mw_year=7134560.0
    * inflate_2007
    / current_electrolyzer_mw,  # fixed cell
    hydrogen_electrolyzer_variable_cost_per_kg=0.0,  # they only count electricity as variable cost
    hydrogen_electrolyzer_kg_per_mwh=current_electrolyzer_kg_per_mwh,
    hydrogen_electrolyzer_life_years=40,  # plant_life cell
    hydrogen_fuel_cell_capital_cost_per_mw=813000 * inflate_2008,  # 46719.pdf
    hydrogen_fuel_cell_fixed_cost_per_mw_year=27000 * inflate_2008,  # 46719.pdf
    hydrogen_fuel_cell_variable_cost_per_mwh=0.0,  # not listed in 46719.pdf; we should estimate a wear-and-tear factor
    hydrogen_fuel_cell_mwh_per_kg=0.53 * h2_mwh_per_kg,  # efficiency from 46719.pdf
    hydrogen_fuel_cell_life_years=15,  # 46719.pdf
    hydrogen_liquefier_capital_cost_per_kg_per_hour=inflate_1995
    * 25600,  # 25106.pdf p. 18, for 1500 kg/h plant, approx. 100 MW
    hydrogen_liquefier_fixed_cost_per_kg_hour_year=0.0,  # unknown, assumed low
    hydrogen_liquefier_variable_cost_per_kg=0.0,  # 25106.pdf p. 23 counts tank, equipment and electricity, but those are covered elsewhere
    hydrogen_liquefier_mwh_per_kg=10.0
    / 1000.0,  # middle of 8-12 range from 25106.pdf p. 23
    hydrogen_liquefier_life_years=30,  # unknown, assumed long
    liquid_hydrogen_tank_capital_cost_per_kg=inflate_1995
    * 18,  # 25106.pdf p. 20, for 300000 kg vessel
    # we don't use min size for tank because that introduces binary variables;
    # we expect the tanks will be larger than this if used in China (and they
    # are in early tests)
    # liquid_hydrogen_tank_minimum_size_kg=300000,  # corresponds to price above; cost/kg might be 800/volume^0.3
    liquid_hydrogen_tank_life_years=40,  # unknown, assumed long
)

# future hydrogen costs
future_hydrogen_info = current_hydrogen_info.copy()
future_hydrogen_info.update(
    hydrogen_electrolyzer_capital_cost_per_mw=58369966
    * inflate_2007
    / future_electrolyzer_mw,  # depr_cap cell
    hydrogen_electrolyzer_fixed_cost_per_mw_year=3560447
    * inflate_2007
    / future_electrolyzer_mw,  # fixed cell
    hydrogen_electrolyzer_variable_cost_per_kg=0.0,  # they only count electricity as variable cost
    hydrogen_electrolyzer_kg_per_mwh=future_electrolyzer_kg_per_mwh,
    hydrogen_electrolyzer_life_years=40,  # plant_life cell
    # table 5, p. 13 of 46719.pdf, low-cost
    # ('The value of $434/kW for the low-cost case is consistent with projected values for stationary fuel cells')
    hydrogen_fuel_cell_capital_cost_per_mw=434000 * inflate_2008,
    hydrogen_fuel_cell_fixed_cost_per_mw_year=20000 * inflate_2008,
    hydrogen_fuel_cell_variable_cost_per_mwh=0.0,  # not listed in 46719.pdf; we should estimate a wear-and-tear factor
    hydrogen_fuel_cell_mwh_per_kg=0.58 * h2_mwh_per_kg,
    hydrogen_fuel_cell_life_years=26,
)
pd.DataFrame(future_hydrogen_info, index=[0]).to_csv(
    "inputs_updated/hydrogen.csv", na_rep=".", index=False
)

###############################
# Add hydrogen fuel cells as generator option (currently using future cost
# in all years, would be good to vary by year)
gen_info = pd.read_csv("inputs_updated/gen_info.csv", na_values=".")
build_costs = pd.read_csv("inputs_updated/gen_build_costs.csv", na_values=".")
load_zones = pd.read_csv("inputs_updated/load_zones.csv", na_values=".")
fuel_cost = pd.read_csv("inputs_updated/fuel_cost.csv", na_values=".")
fuels = pd.read_csv("inputs_updated/fuels.csv", na_values=".")
# this still has extra columns for fuel cells from previous models
hydrogen = pd.read_csv("inputs_updated/hydrogen.csv", na_values=".").iloc[0, :]
build_years = pd.read_csv("inputs_updated/periods.csv")[["INVESTMENT_PERIOD"]].rename(
    {"INVESTMENT_PERIOD": "build_year"}, axis=1
)

hydrogen_mmbtu_per_kg = 0.113745  # see hydrogen_supply.py
battery = gen_info[
    gen_info["GENERATION_PROJECT"] == "Anhui-Battery_Storage-11177"
].iloc[0, :]

new_gi = pd.DataFrame(
    {
        "GENERATION_PROJECT": load_zones["LOAD_ZONE"] + "_Fuel_Cell",
        "gen_tech": "Fuel_Cell",
        "gen_energy_source": "Hydrogen",
        "gen_load_zone": load_zones["LOAD_ZONE"],
        "gen_max_age": hydrogen["hydrogen_fuel_cell_life_years"],
        "gen_is_variable": False,
        "gen_is_baseload": False,
        "gen_can_provide_spinning_reserves": True,
        "gen_full_load_heat_rate": hydrogen_mmbtu_per_kg
        / hydrogen["hydrogen_fuel_cell_mwh_per_kg"],
        "gen_variable_om": hydrogen["hydrogen_fuel_cell_variable_cost_per_mwh"],
        # duplicate some data from batteries
        "gen_connect_cost_per_mw": battery["gen_connect_cost_per_mw"],
        "gen_scheduled_outage_rate": battery["gen_scheduled_outage_rate"],
        "gen_forced_outage_rate": battery["gen_forced_outage_rate"],
        "gen_is_cogen": False,
        # proxy for energy delivered due to occasional "up" operations while
        # providing reserves; also prevents provision of reserves with no
        # hydrogen production
        "gen_min_load_fraction": 0.03,
    },
    columns=gen_info.columns,
)
gen_info = pd.concat([gen_info, new_gi], axis=0)

new_bc = pd.DataFrame(
    {
        "GENERATION_PROJECT": new_gi.loc[:, "GENERATION_PROJECT"],
        "gen_overnight_cost": hydrogen["hydrogen_fuel_cell_capital_cost_per_mw"],
        "gen_fixed_om": hydrogen["hydrogen_fuel_cell_fixed_cost_per_mw_year"],
    }
)
# cross join with build_years, using a dummy join
new_bc = new_bc.assign(key="x").merge(build_years.assign(key="x")).drop("key", axis=1)
build_costs = pd.concat([build_costs, new_bc], axis=0)

new_fc = pd.DataFrame(
    {"load_zone": load_zones["LOAD_ZONE"], "fuel": "Hydrogen", "fuel_cost": 0.0}
)
# cross join with periods, using a dummy join
new_fc = (
    new_fc.assign(key="x")
    .merge(build_years.rename({"build_year": "period"}, axis=1).assign(key="x"))
    .drop("key", axis=1)
)
fuel_cost = pd.concat([fuel_cost, new_fc], axis=0)

new_fuels = pd.DataFrame({"fuel": "Hydrogen", "co2_intensity": 0.0}, index=[0])
fuels = pd.concat([fuels, new_fuels], axis=0)

gen_info.to_csv("inputs_updated/gen_info.csv", na_rep=".", index=False)
build_costs.to_csv("inputs_updated/gen_build_costs.csv", na_rep=".", index=False)
fuel_cost.to_csv("inputs_updated/fuel_cost.csv", na_rep=".", index=False)
fuels.to_csv("inputs_updated/fuels.csv", na_rep=".", index=False)


#######################
# Add CCS and Hydrogen retrofit versions of all coal projects
#
# This is modeled as an additional plant labeled as a retrofit (with incremental
# capital and fixed O&M costs for retrofit and total variable costs and heat
# rate) Then we use retrofits.py to impose a side constraint that requires the
# base plant to exist and prevents commitment of both base and retrofit plant at
# same time.
#
# from cheapest technology in https://doi.org/10.1016/j.jclepro.2022.135696
# (supplementary spreadsheet), EEDIDA in TSF configuration; see
# "ccs retrofit.xlsx" in this folder for a version that rescales this plant to
# have the same gross (pre-CCS) output as the reference plant, used for the
# calculations below:
# - extra energy (reduction in output after adding CCS): 1 - 594287/649930 = 0.0856
# - rescale heat rate for gross output (Switch uses this heat rate for both net
#   output and work done for the CCS system; we assume extra heat needed is
#   proportional to heat input, i.e., CO2 production): 9178/8473 = 1.0832
# - CO2 capture efficacy (J37): 0.90
# - extra capital cost for CCS (we count only the CO2 removal system and
#   compressor and drying, since the rest are nearly a wash): $922/kWe
# - extra fixed O&M, absolute (property taxes and insurance, which we assume
#   is proportional to CCS system cost, which is fixed):
#   41845-27281 = $14564/MW-year
# - extra fixed O&M, scaled vs. base case: (labor, which we assume scales up at
#   the same proportion in China): 24325/18585 - 1 = 0.3089
# - new variable O&M, scale (non-CO2 costs, due to greater heat input):
#   48050/37372 = 1.2857
# - extra variable O&M, absolute (CO2-related materials, assumed same cost in
#   China): 15,060,000 / (649.930 gross MW * 0.85 * 8760) = $3.1120/MWh

# note: below, we assume CCS costs are given for the same financial year as ATB

gen_info = pd.read_csv("inputs_updated/gen_info.csv", na_values=".")
new_gi_base = gen_info.query('gen_energy_source == "Coal"').copy()
coal_projects = new_gi_base["GENERATION_PROJECT"]
gen_build_costs = pd.read_csv("inputs_updated/gen_build_costs.csv", na_values=".")
new_bc_base = gen_build_costs.merge(coal_projects, on="GENERATION_PROJECT").query(
    "build_year >= 2023"
)
gen_retrofits = pd.DataFrame()

for retrofit in ["CCS", "H2"]:
    new_gi = new_gi_base.copy()
    for col in ["GENERATION_PROJECT", "gen_dbid", "gen_tech"]:
        new_gi[col] = new_gi[col] + "_" + retrofit
    if retrofit == "CCS":
        # add new rows to gen_info with CCS efficacy and energy load
        new_gi["gen_ccs_capture_efficiency"] = 0.90
        new_gi["gen_ccs_energy_load"] = 0.0856
        # below we use $3/MWh (2010) as the baseline variable O&M, since that's mainly what's
        # shown for non-IGCC plants, which match the reference plant above
        new_gi["gen_variable_om"] = (
            new_gi["gen_variable_om"]
            + 3 * 0.2857 * switch_china_deflator
            + (3.1120 * atb_deflator)
        )
    elif retrofit == "H2":
        # just change the fuel; everything else in gen_info is unchanged
        new_gi["gen_energy_source"] = "Hydrogen"

    gen_info = pd.concat([gen_info, new_gi], axis=0)

    # fill in gen_build_costs (*extra* capital and fixed O&M costs for retrofit)
    new_bc = new_bc_base.copy()
    new_bc["GENERATION_PROJECT"] = new_bc["GENERATION_PROJECT"] + "_" + retrofit

    if retrofit == "CCS":
        new_bc["gen_overnight_cost"] = 922000 * atb_deflator
        # below we use $5580/MW-y (2010) as the baseline fixed O&M, since that's the mean of
        # the non-IGCC plants, which match the reference plant above (IGCC has $15,000
        # fixed O&M, but that shouldn't carry through to the CCS retrofit)
        # starting 8/29, retrofits should show additional capital cost but full
        # fixed O&M cost for the retrofit, so we add this to previous fixed O&M
        new_bc["gen_fixed_om"] += 0.3089 * 5580 * switch_china_deflator + (
            14564 * atb_deflator
        )
    elif retrofit == "H2":
        # arbitrary $10/kW for burner retrofit (not clear if IGCC would be
        # so easy, but we leave it like this for now)
        new_bc["gen_overnight_cost"] = 10000
        # assume no additional O&M  cost (maybe lower than coal)
        new_bc["gen_fixed_om"] += 0.0

    gen_build_costs = pd.concat([gen_build_costs, new_bc], axis=0)

    # add to gen_retrofits.csv
    gen_retrofits = pd.concat(
        [
            gen_retrofits,
            pd.DataFrame(
                {
                    "base_gen_project": coal_projects,
                    "retrofit_gen_project": coal_projects + "_" + retrofit,
                }
            ),
        ],
        axis=0,
    )

# save the new versions with retrofit technologies
gen_info.to_csv("inputs_updated/gen_info.csv", na_rep=".", index=False)
gen_build_costs.to_csv("inputs_updated/gen_build_costs.csv", na_rep=".", index=False)
gen_retrofits.to_csv("inputs_updated/gen_retrofits.csv", index=False)

# create versions with H2 but without CCS
gen_info.query("not GENERATION_PROJECT.str.endswith('_CCS')").to_csv(
    "inputs_updated/gen_info.no_ccs.csv", na_rep=".", index=False
)
gen_build_costs.query("not GENERATION_PROJECT.str.endswith('_CCS')").to_csv(
    "inputs_updated/gen_build_costs.no_ccs.csv", na_rep=".", index=False
)
gen_retrofits.query("not retrofit_gen_project.str.endswith('_CCS')").to_csv(
    "inputs_updated/gen_retrofits.no_ccs.csv", na_rep=".", index=False
)


##################
# Add the hydrogen and retrofit modules to modules.txt to support the
# hydrogen and CCS versions of the generators.
with open("inputs_updated/modules.txt") as f:
    lines = f.readlines()
if not lines[-1].endswith("\n"):
    lines[-1] += "\n"
lines.append("study_modules.gen_retrofits_with_retirement\n")
lines.append("study_modules.hydrogen_supply\n")
with open("inputs_updated/modules.txt", "w") as f:
    f.writelines(lines)

# %%##################################
# Use 2028, 2038, 2048, and optionally 2058 and 2068 instead of every
# 5 years from 2023-2048.
# The longer series ensures we include most or all of the cost of fossil
# plants built in 2048 or earlier that may not be
# Update
# capacity_plans, total_capacity_limits,
# carbon_policies,
# fuel_cost, fuel_supply_curves,
# gen_build_costs,
# loads, variable_capacity_factors,
# periods, timepoints, timeseries,
# zone_coincident_peak_demand

for new_dir in ["inputs_extended", "inputs_sparse"]:
    extend = new_dir == "inputs_extended"

    # Copy base directory to new one, then write some custom files there.
    mkdir(new_dir)

    timeless_tables = [
        "financials",
        "gen_info",
        "gen_info.no_ccs",
        "gen_info.no_ccs_h2",
        "gen_build_predetermined",
        "gen_part_load_heat_rates",
        "gen_retrofits",
        "gen_retrofits.no_ccs",
        "load_zones",
        "trans_params",
        "transmission_lines",
        "fuels",
        "non_fuel_energy_sources",
        "regional_fuel_markets",
        "zone_to_regional_fuel_market",
        "planning_reserve_requirements",
        "planning_reserve_requirement_zones",
        "hydrogen",
    ]
    for f in timeless_tables:
        shutil.copy2(
            os.path.join("inputs_updated", f + ".csv"),
            os.path.join(new_dir, f + ".csv"),
        )
    for f in [
        "switch_inputs_version.txt",
        "modules.txt",
        "modules.no_suspend.txt",
        "modules.no_ccs_h2.txt",
    ]:
        shutil.copy2(
            os.path.join("inputs_updated", f),
            os.path.join(new_dir, f),
        )

    # These need custom treatment:
    # periods, timepoints, timeseries,
    period_list = [2028, 2038, 2048]
    if extend:
        period_list += [2058, 2068]
    periods = pd.DataFrame({"INVESTMENT_PERIOD": period_list})
    periods["period_start"] = periods["INVESTMENT_PERIOD"]
    periods["period_end"] = periods["period_start"] + 9
    periods.to_csv(os.path.join(new_dir, "periods.csv"), index=False)

    timeseries = (
        pd.read_csv("inputs_updated/timeseries.csv")
        .merge(
            periods[["INVESTMENT_PERIOD"]],
            left_on="ts_period",
            right_on="INVESTMENT_PERIOD",
        )
        .drop("INVESTMENT_PERIOD", axis=1)
    )
    # double the weights to cover 10 years instead of 5
    timeseries["ts_scale_to_period"] *= 2

    # add extra periods if needed
    if extend:
        for p in [2058, 2068]:
            new = timeseries.query("ts_period == 2048").copy()
            new.loc[:, "ts_period"] = p
            new["TIMESERIES"] = new["TIMESERIES"].str.replace("2050", str(p + 2))
            timeseries = pd.concat([timeseries, new], axis=0)

    timeseries.to_csv(os.path.join(new_dir, "timeseries.csv"), index=False)

    timepoints = (
        pd.read_csv("inputs_updated/timepoints.csv")
        .merge(timeseries[["TIMESERIES"]], left_on="timeseries", right_on="TIMESERIES")
        .drop("TIMESERIES", axis=1)
    )
    if extend:
        for p in [2058, 2068]:
            new_tag = str(p + 2)
            new = timepoints[timepoints["timeseries"].str.startswith("2050.")].copy()
            new["timepoint_id"] = new["timepoint_id"].str.replace("2050", new_tag)
            new["timestamp"] = new["timestamp"].str.replace("2050", new_tag)
            new["timeseries"] = new["timeseries"].str.replace("2050", new_tag)
            timepoints = pd.concat([timepoints, new], axis=0)

    timepoints.to_csv(os.path.join(new_dir, "timepoints.csv"), index=False)

    # all these files just need to be filtered by the "period" column and have the
    # 2048 row repeated as 2058 and 2068 rows
    period_tables = [
        "capacity_plans",
        "total_capacity_limits",
        "carbon_policies",
        "carbon_policies_price_200",
        "fuel_cost",
        "fuel_supply_curves",
        ("gen_build_costs", "build_year"),
        ("gen_build_costs.no_ccs_h2", "build_year"),
        ("gen_build_costs.no_ccs", "build_year"),
        "zone_coincident_peak_demand",
    ]
    period_tables += sorted(
        n[:-4] for n in glob.glob("carbon_policies_???.csv", root_dir="inputs_updated")
    )

    for x in period_tables:
        try:
            tbl, col = x
        except ValueError:  # not a tuple
            tbl, col = x, "period"
        df = pd.read_csv(os.path.join("inputs_updated", tbl + ".csv"), na_values=".")
        if not col in df.columns:
            # try capitalizing
            col = col.upper()
        if tbl.startswith("gen_build_costs"):
            # for gen_build_costs, we have to keep both the gen_build_predetermined
            # list (including some in 2023) and the new study periods
            predet = pd.read_csv(
                "inputs_updated/gen_build_predetermined.csv", na_values="."
            )
            predet_rows = df.merge(predet[["GENERATION_PROJECT", "build_year"]])
            df = pd.concat([predet_rows, df.loc[df[col].isin([2028, 2038, 2048]), :]])
        else:
            df = df.loc[df[col].isin([2028, 2038, 2048]), :]

        if extend:
            for p in [2058, 2068]:
                new_row = df.loc[df[col] == 2048, :].copy()
                new_row.loc[:, col] = p
                df = pd.concat([df, new_row], axis=0)

        df = df.sort_values(df.columns.to_list())
        df.to_csv(os.path.join(new_dir, tbl + ".csv"), na_rep=".", index=False)

    timepoint_tables = [
        "loads",
        "variable_capacity_factors",
    ]
    for tbl in timepoint_tables:
        col = "timepoint"
        df = pd.read_csv(os.path.join("inputs_updated", tbl + ".csv"), na_values=".")
        if col not in df.columns:
            col = col.upper()
        # drop if not found in new timepoints file
        df = df.merge(
            timepoints["timepoint_id"], left_on=col, right_on="timepoint_id"
        ).drop("timepoint_id", axis=1)

        if extend:
            for p in [2058, 2068]:
                new = df[df[col].str.startswith("2050.")].copy()
                new[col] = new[col].str.replace("2050", str(p + 2))
                df = pd.concat([df, new], axis=0)

        df.to_csv(os.path.join(new_dir, tbl + ".csv"), na_rep=".", index=False)

    timeseries_tables = [
        "hydro_timeseries"
    ]  # not created till later: "hydrogen_tank_reserve_days"

    for tbl in timeseries_tables:
        col = "timeseries"
        df = pd.read_csv(os.path.join("inputs_updated", tbl + ".csv"), na_values=".")
        if col not in df.columns:
            col = col.upper()
        # drop if not found in new timeseries file
        df = df.merge(timeseries["TIMESERIES"], left_on=col, right_on="TIMESERIES")
        if col == "timeseries":
            df = df.drop("TIMESERIES", axis=1)
        if extend:
            for p in [2058, 2068]:
                new = df[df[col].str.startswith("2050.")].copy()
                new[col] = new[col].str.replace("2050", str(p + 2))
                df = pd.concat([df, new], axis=0)

        df.to_csv(os.path.join(new_dir, tbl + ".csv"), na_rep=".", index=False)


# %%##################################
# Everything above wrote to the inputs_sparse or inputs_extended directory. Now
# we create <base_dir>_reserves directories based on those. These have extra timeseries
# with higher load and low weight, to represent rare conditions with extra-high
# load or low renewables. The default is 10% extra load, but loads.res20.csv and
# loads.res30.csv give higher super-peak loads.

# The tough days are found by running the inputs_extended model with 0% and 200%
# carbon limits, with planning reserves turned off and spinning reserves (3+5)
# turned on. (no spinning reserve rule was applied in the original model,
# probably by accident). This is done by the `switch solve-scenarios
# --scenario-list scenarios_find_expensive_days.txt` command below. Then we find
# days with the highest load-weighted marginal cost from energy_sources.csv.

co2_levels = ["000", "200"]
with open("scenarios_find_expensive_days.txt", "w") as f:
    for co2_level in co2_levels:
        f.write(
            f"--scenario-name {co2_level} --input-alias carbon_policies.csv=carbon_policies_{co2_level}.csv --outputs-dir out_tough_days/carbon_{co2_level}_spin_only --inputs-dir inputs_extended --exclude-module switch_model.balancing.planning_reserves --include-module study_modules.spinning_reserves_35\n"
        )

run = input(
    "Would you like to solve the scenarios to find difficult days to serve?\n"
    "If not, previous results will be used if available. y/[n] "
)
if run in {"y", "yes"}:
    with tempfile.TemporaryDirectory() as sq:
        cmd = f"switch solve-scenarios --scenario-list scenarios_find_expensive_days.txt --debug --scenario-queue {sq}"
        subprocess.run(cmd.split(), check=True)

# find dates to duplicate
new_ts = pd.DataFrame()
for co2_level in co2_levels:
    es = pd.read_csv(
        f"out_tough_days/carbon_{co2_level}_spin_only/energy_sources_{co2_level}.csv"
    )
    es["expenditure"] = es["zone_demand_mw"] * es["marginal_cost"]
    es["timeseries"] = es["timepoint_label"].str[:10].str.replace("-", ".")
    daily = es.groupby(["period", "timeseries"])[
        ["zone_demand_mw", "expenditure"]
    ].sum()
    daily["mean_price"] = daily["expenditure"] / daily["zone_demand_mw"]
    # are high load days the expensive ones?
    # daily.xs(2048, level="period").plot.scatter(x="zone_demand_mw", y="mean_price")
    expensive = daily.loc[daily.groupby("period")["mean_price"].idxmax()]
    ts = expensive.index.to_frame(index=False)
    ts["new_timeseries"] = (
        ts["period"].astype(str) + ".res." + co2_level
    )  # must not look like a float
    new_ts = pd.concat([new_ts, ts[["timeseries", "new_timeseries"]]], axis=0)

# we make versions of both sparse and extended so we can see how much that
# matters with reserve requirements in place
for base_dir in ["inputs_extended", "inputs_sparse"]:
    new_dir = f"{base_dir}_reserves"

    # Copy base directory to new_dir, then update files there.
    copydir(base_dir, new_dir)

    # Remove switch_model.balancing.planning_reserves because it applies
    # unusable fossil plants to meet PRM; instead we use a spinning reserves and
    # add a day with extra load. Note that outage derating gives about a 5%
    # margin and adding a 10% super-peak load day (later) gets us up to a 15%
    # planning reserve margin, similar to the planning_reserves module, but in a
    # more reliable way.
    for mod_file in [
        "modules.txt",
        "modules.no_suspend.txt",
        "modules.no_ccs_h2.txt",
    ]:
        lines = []
        with open(os.path.join(new_dir, mod_file)) as f:
            for line in f:
                if line.strip() == "switch_model.balancing.planning_reserves":
                    line = "# (removed) " + line
                lines.append(line)
        # add module to apply 3+5 rule even if not specified
        # (original model didn't specify a rule, so it didn't run with
        # spinning reserves)
        if not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append("study_modules.spinning_reserves_35\n")
        if not "no_ccs_h2" in mod_file:
            # build enough hydrogen storage capacity to cover the reserve days
            lines.append("study_modules.hydrogen_tank_reserves\n")
        with open(os.path.join(new_dir, mod_file), "w") as f:
            f.writelines(lines)

    # update timeseries, timepoints, hydro_timeseries, loads,
    # variable_capacity_factors

    # add new difficult days to timeseries with weights equivalent to 15 days each (30 total)
    # every 3 years, i.e., a 30-day heat wave every 3 years. This is 50 days each in 10 years.
    timeseries = pd.read_csv(os.path.join(new_dir, "timeseries.csv"), na_values=".")
    new = (
        new_ts.rename({"timeseries": "TIMESERIES"}, axis=1)
        .merge(timeseries)
        .drop("TIMESERIES", axis=1)
        .rename({"new_timeseries": "TIMESERIES"}, axis=1)
        .assign(ts_scale_to_period=50)  # treat each sample as 50-in-10-years
    )
    # reduce weight on the others to make room for the extra 100 heat wave days
    # per 10 years
    timeseries["ts_scale_to_period"] *= 1 - (100 / 3650)
    timeseries = pd.concat([timeseries, new], axis=0)
    timeseries.to_csv(os.path.join(new_dir, "timeseries.csv"), na_rep=".", index=False)

    # save hydrogen_tank_reserve_days.csv to increase hydrogen availability to
    # reflect the fact that these events occur every 3 years, but are 3 times as
    # long when they do occur
    occurrences = new[["TIMESERIES"]].assign(ts_years_between_occurrence=3)
    occurrences.to_csv(
        os.path.join(new_dir, "hydrogen_tank_reserve_days.csv"), na_rep=".", index=False
    )

    timepoints = pd.read_csv(os.path.join(new_dir, "timepoints.csv"), na_values=".")
    new = (
        new_ts.merge(timepoints)
        .drop("timeseries", axis=1)
        .rename({"new_timeseries": "timeseries"}, axis=1)
        .rename({"timepoint_id": "timepoint"}, axis=1)
    )
    # add ".000" or ".200" (emission level for tough-day scenario) tag to timepoint
    new["new_timepoint"] = new["timepoint"] + new["timeseries"].str[-4:]
    # save new timepoints to use in other files
    new_tp = new[["timepoint", "new_timepoint"]]
    new = new.drop("timepoint", axis=1).rename(
        {"new_timepoint": "timepoint_id"}, axis=1
    )
    # move the peak dates into a different calendar year for graphing
    new["timestamp"] = new["timestamp"].str[:3] + "1" + new["timestamp"].str[4:]
    timepoints = pd.concat([timepoints, new], axis=0)
    timepoints.to_csv(os.path.join(new_dir, "timepoints.csv"), na_rep=".", index=False)

    timeseries_tables = ["hydro_timeseries", "hydrogen_tank_reserve_days"]
    for t in timeseries_tables:
        file = os.path.join(new_dir, t + ".csv")
        df = pd.read_csv(file, na_values=".")
        col = "timeseries"
        if col not in df.columns:
            col = col.upper()
        new = new_ts.merge(df, left_on="timeseries", right_on=col)
        new[col] = new["new_timeseries"]  # put in same place as original col
        new = new.drop("new_timeseries", axis=1)
        if col != "timeseries":
            new = new.drop("timeseries", axis=1)
        df = pd.concat([df, new], axis=0)
        df.to_csv(file, na_rep=".", index=False)

    timepoint_tables = ["loads", "variable_capacity_factors"]
    for t in timepoint_tables:
        file = os.path.join(new_dir, t + ".csv")
        df = pd.read_csv(file, na_values=".")
        col = "timepoint"
        if col not in df.columns:
            col = col.upper()
        new = new_tp.merge(df, left_on="timepoint", right_on=col)
        new[col] = new["new_timepoint"]  # put in same place as original col
        new = new.drop("new_timepoint", axis=1)
        if col != "timepoint":
            new = new.drop("timepoint", axis=1)
        if t == "loads":
            # raise tough-day loads by 10, 20 or 30%
            for reserve_level in [0.1, 0.2, 0.3]:
                res = new.copy()
                res["zone_demand_mw"] *= 1 + reserve_level
                final_df = pd.concat([df, res], axis=0)
                final_df.to_csv(
                    file.replace("loads.", f"loads.res{int(reserve_level*100):02d}."),
                    na_rep=".",
                    index=False,
                )
                if reserve_level == 0.1:
                    # use 10% as the base case too
                    final_df.to_csv(file, na_rep=".", index=False)
        else:
            final_df = pd.concat([df, new], axis=0)
            final_df.to_csv(file, na_rep=".", index=False)

# %% Define scenarios for the study

themes = [
    {
        "scen": "reserves_10",
        "in_dir": "inputs_extended_reserves",
        "extra": "--input-alias loads.csv=loads.res10.csv",
    },
    {"scen": "reserves_10_sparse", "in_dir": "inputs_sparse_reserves", "extra": ""},
    {
        "scen": "reserves_10_no_ccs_h2",
        "in_dir": "inputs_extended_reserves",
        "extra": "--module-list inputs_extended_reserves/modules.no_ccs_h2.txt --input-aliases gen_build_costs.csv=gen_build_costs.no_ccs_h2.csv gen_info.csv=gen_info.no_ccs_h2.csv",
    },
    {
        "scen": "reserves_10_no_ccs",
        "in_dir": "inputs_extended_reserves",
        "extra": "--input-aliases gen_build_costs.csv=gen_build_costs.no_ccs.csv gen_info.csv=gen_info.no_ccs.csv gen_retrofits.csv=gen_retrofits.no_ccs.csv",
    },
    {
        "scen": "reserves_20",
        "in_dir": "inputs_extended_reserves",
        "extra": "--input-alias loads.csv=loads.res20.csv",
    },
    {
        "scen": "reserves_30",
        "in_dir": "inputs_extended_reserves",
        "extra": "--input-alias loads.csv=loads.res30.csv",
    },
    {
        "scen": "spin_only",
        "in_dir": "inputs_extended",
        "extra": "--exclude-module switch_model.balancing.planning_reserves --include-module spinning_reserves_35",
    },
]

# originally scenarios_heat_waves / out_heat_waves
with open("scenarios_carbon_cap.txt", "w") as f:
    for theme in themes:
        scen = theme["scen"]
        in_dir = theme["in_dir"]
        extra = theme["extra"]
        for cap_level in carbon_caps:
            cap = f"{cap_level:03d}"
            f.write(
                f"--scenario-name carbon_{cap}_{scen} --inputs-dir {in_dir} --outputs-dir out_carbon_cap/carbon_{cap}_{scen} --input-alias carbon_policies.csv=carbon_policies_{cap}.csv {extra}\n"
            )
