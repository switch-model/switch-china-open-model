# %% setup
import pandas as pd, numpy as np
import matplotlib.pyplot as plt
import matplotlib.transforms as mpl_trans
import os, glob

# show numbers nicely
# pd.set_option("display.float_format", "{:,.0f}".format)


def assign_categories(df):
    df = df.copy()
    df["cat"] = df["gen_energy_source"]
    df.loc[df["cat"] == "Uranium", "cat"] = "Nuclear"
    df.loc[df["cat"] == "Water", "cat"] = "Hydro"
    df.loc[df["gen_tech"] == "Battery_Storage", "cat"] = "Batteries"
    df.loc[df["gen_tech"].str.endswith("_H2"), "cat"] += " (Coal Retrofit)"
    df.loc[df["gen_tech"].str.endswith("_CCS"), "cat"] += " (CCS)"
    df.loc[df["gen_tech"] == "Fuel_Cell", "cat"] += " (Fuel Cell)"
    df.loc[df["cat"] == "Coal", "cat"] += " (Direct)"
    return df


def read_scenario(scenario_dir):
    cap = pd.read_csv(f"{scenario_dir}/gen_cap.csv")
    cap = cap.rename(
        {"GENERATION_PROJECT": "gen", "PERIOD": "period", "GenCapacity": "cap_mw"},
        axis=1,
    )
    cap = assign_categories(cap)

    cap_sum = cap.groupby(["period", "cat"])["cap_mw"].sum() / 1000  # GW

    dis = pd.read_csv(f"{scenario_dir}/dispatch_annual_summary.csv")
    dis = assign_categories(dis)
    dis_sum = (
        dis.groupby(["period", "cat"])["Energy_GWh_typical_yr"].sum() / 1000
    )  # TWh

    carbon_cost = pd.read_csv(f"{scenario_dir}/emissions.csv", na_values=".").set_index(
        "PERIOD"
    )
    carbon_cost["carbon_cap_dual_future_dollar_per_tco2"] *= -1  # fix sign
    # use specified price if there was no cap
    carbon_cost["carbon_cap_dual_future_dollar_per_tco2"] = carbon_cost[
        "carbon_cap_dual_future_dollar_per_tco2"
    ].fillna(carbon_cost["carbon_cost_dollar_per_tco2"])
    carbon_cost = carbon_cost["carbon_cap_dual_future_dollar_per_tco2"]

    carbon = (
        pd.read_csv(f"{scenario_dir}/emissions.csv")
        .set_index("PERIOD")
        .loc[:, "AnnualEmissions_tCO2_per_yr"]
    )

    # the electricity_cost.csv file uses incorrect conversions in Switch 2.0.7
    # and earlier, so we use the summary file instead.
    summary = pd.read_csv(glob.glob(f"{scenario_dir}/summary_*.csv")[0])
    summary = summary.loc[
        :, [c for c in summary.columns if c.startswith("cost_per_kwh_")]
    ]
    summary.index = ["LCOE"]
    summary.columns = [int(c[-4:]) for c in summary.columns]
    electricity_cost = summary.T * 1000  # $/MWh
    return cap_sum, dis_sum, carbon_cost, carbon, electricity_cost


def set_resource_order(df, axis):
    if axis == 0:  # index
        plot_order = [r for r in resource_plot_order if r in df.index] + [
            r for r in df.index if r not in resource_plot_order
        ]
        return df.loc[plot_order, :]
    elif axis == 1:  # columns
        plot_order = [r for r in resource_plot_order if r in df.columns] + [
            r for r in df.columns if r not in resource_plot_order
        ]
        return df.loc[:, plot_order]
    else:
        return df


# order of resources from bottom (most firm) up
resource_colors = {
    "Nuclear": "#CCCC42",  # "peru",
    "Hydro": "blue",
    "Gas": "lightgray",
    "Coal (Direct)": "#5F360F",  # "black",
    "Coal (CCS)": "#B4967A",  # "dimgray",
    "Hydrogen (Coal Retrofit)": "purple",
    "Hydrogen (Fuel Cell)": "crimson",
    "Batteries": "green",
    "Wind": "lightskyblue",  # "#A3CBFA",  # "cornflowerblue",
    "Solar": "orange",  # "#F19E38",  # "orange",
}
# could try to add retirements with cross-hatching, but they're too small too see
# and they clutter the legend (and I haven't found a great way to identify the
# right patches to cross-hatch)
# resource_colors.update({f"{r}, retired": c for (r, c) in resource_colors.items()})
# resource_hatch = [False] * int(len(resource_colors) / 2) + [True] * int(
#     len(resource_colors) / 2
# )
resource_plot_order = list(resource_colors.keys())

# %% ####################
# prepare main diagnostic graphs

# show 2048 capacity and energy plan for "everything on the table" model, as
# 2048 target goes from 200% of 2028 to 0%. Mark where the CO2 cost crosses
# $200. This shows that hydrogen and/or CCS can play a role, but only if you
# push above $200/tCO2, i.e., beyond the cost-effective point. Also plot how
# 2048 LCOE changes as you move across these scenarios. (scenarios_carbon_cap.txt)

carbon_levels = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 40, 50, 60, 80, 100]

group = "out_carbon_cap"
bbox = None

for theme in [
    "reserves_10",
    "reserves_10_no_ccs",
    "reserves_10_no_ccs_h2",
    "reserves_10_sparse",
    "reserves_20",
    "reserves_30",
    "spin_only",
]:
    cap_cross = pd.DataFrame()
    dis_cross = pd.DataFrame()
    carbon_cost_cross = pd.DataFrame()
    electricity_cost_cross = pd.DataFrame()

    for carbon_level in carbon_levels:
        scenario_dir = os.path.join(group, f"carbon_{carbon_level:03d}_{theme}")
        if not os.path.exists(os.path.join(scenario_dir, "gen_cap.csv")):
            # some scenarios don't cover all carbon prices
            print(f"skipping missing scenario {scenario_dir}")
            continue

        cap_sum, dis_sum, carbon_cost, carbon, electricity_cost = read_scenario(
            scenario_dir
        )

        cap_cross[100 - carbon_level] = cap_sum
        dis_cross[100 - carbon_level] = dis_sum
        carbon_cost_cross[100 - carbon_level] = carbon_cost
        electricity_cost_cross[100 - carbon_level] = electricity_cost

    # filter to 2048
    cap_cross = cap_cross.sort_index(axis=1).xs(2048, level="period")
    dis_cross = dis_cross.sort_index(axis=1).xs(2048, level="period")
    carbon_cost_cross = carbon_cost_cross.sort_index(axis=1).loc[2048, :]
    electricity_cost_cross = electricity_cost_cross.sort_index(axis=1).loc[2048, :]

    # sort resources as needed
    cap_cross = set_resource_order(cap_cross, axis=0)
    dis_cross = set_resource_order(dis_cross, axis=0)

    # find reduction level that gives $200/tCO2 emissions
    level_200 = np.interp(200, carbon_cost_cross.values, carbon_cost_cross.index.values)

    def add_level_200_line(ax, label=False):
        ax.plot(
            [level_200] * 2,
            ax.get_ylim(),
            label="$200/tCO2" if label else None,
            linestyle="dotted",
            color="black",
        )

    # make plots
    fig, axes = plt.subplots(
        nrows=4, sharex=True, figsize=(5, 5), height_ratios=[5, 5, 1, 1]
    )

    # capacity plot
    ax = axes[0]
    add_level_200_line(ax, label=True)  # get this into the legend first
    x = cap_cross.clip(lower=0).T.plot.area(
        legend=False,
        color=resource_colors,
        linewidth=0,
        ax=ax,
        ylabel="generator\ncapacity\n(GW)",
        ylim=[0, 13000],
    )
    add_level_200_line(ax)  # plot again without label to show in front
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    # for c in ax.collections: # https://stackoverflow.com/a/49594072
    #     # this sort of works, but it turns on the border for all the patches,
    #     # which clutters the graph; also unclear how to hatch only the retired
    #     # ones and how to leave the retired ones out of the legend (gets
    #     # confusing)
    #     c.set_linewidth(0.5)
    #     c.set_edgecolor('black')
    #     c.set_hatch('///')

    lg = ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", reverse=True)
    lg.get_frame().set_linewidth(0.0)

    # dispatch plot
    ax = axes[1]
    # leave out slightly negative gas values when plotting
    dis_cross.clip(lower=0).T.plot.area(
        legend=False,
        color=resource_colors,
        linewidth=0,
        ax=ax,
        ylabel="electricity\nproduction\n(TWh)",
        ylim=[0, 18000],
    )
    add_level_200_line(ax)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))

    # carbon cost plot
    ax = axes[2]
    carbon_cost_cross.plot(
        ax=ax,
        ylim=[0, 400],
        color="blue",
        ylabel="marg.\nCO2\ncost\n($/\ntCO2)",
    )
    add_level_200_line(ax)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))

    # LCOE plot
    ax = axes[3]
    electricity_cost_cross.plot(
        ax=ax,
        ylim=[0, 150],
        color="blue",
        ylabel="LCOE\n($/\nMWh)",
        xlabel="Emission reductions vs. baseline (%)",
    )
    add_level_200_line(ax)
    ax.xaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:.0f}%"))
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))

    # annotate $200/tCO2 emission reduction level
    # ax.plot(
    #     [level_200, level_200],
    #     [-5, 0],
    #     linestyle="dotted",
    #     color="black",
    # )
    ax.annotate(
        f"{level_200:0.1f}%",
        xy=(level_200, 0),
        xycoords="data",
        xytext=(0, -30),
        textcoords="offset points",
        arrowprops=dict(
            arrowstyle="-", linestyle=(0, (1, 3))
        ),  # 0=dotted; see https://matplotlib.org/stable/gallery/lines_bars_and_markers/linestyles.html
        horizontalalignment="center",
        verticalalignment="bottom",
        annotation_clip=False,
    )

    # get suitable bounding box dimensions from first figure and
    # reuse across the rest
    # https://stackoverflow.com/a/28698105/3830997
    if bbox is None:
        bbox = fig.get_tightbbox()

    # expand bounding box as needed during save to include the legend
    outdir = os.path.join(group, "figures")
    os.makedirs(outdir, exist_ok=True)
    fig.savefig(os.path.join(outdir, f"abatement_curve_{theme}.pdf"), bbox_inches=bbox)

# %% show capacity and energy transition over 2028-2068. Goal is to see whether
#    coal/CCS comes in early then phases out as it ages out. (It doesn't.)

group = "out_stepwise"
bbox = None
summary = pd.DataFrame()

for scen in [
    "step_9_tough_day_reserves_10",
    "step_9a_no_ccs",
    "step_9aa_no_ccs_no_h2",
    "step_0_original",
]:
    # gather capacity and dispatch data
    # scenario_dir = "out_carbon_cap/carbon_005_reserves_10")
    # scenario_dir = "out_stepwise/step_9_tough_day_reserves_10"
    scenario_dir = os.path.join(group, scen)

    cap_sum, dis_sum, carbon_cost, carbon, electricity_cost = read_scenario(
        scenario_dir
    )

    cap_sum = set_resource_order(cap_sum.unstack(), axis=1)
    dis_sum = set_resource_order(dis_sum.unstack(), axis=1)

    # filter to 2048 or earlier
    cap_sum = cap_sum.loc[2028:2048, :]
    dis_sum = dis_sum.loc[2028:2048, :]
    carbon_cost = carbon_cost.loc[2028:2048]
    carbon = carbon.loc[2028:2048]
    electricity_cost = electricity_cost.loc[2028:2048, :]

    # Convert to percent of 2028 levels
    # carbon = carbon / 4856000000
    # Convert to millions of tonnes
    carbon /= 1e6

    fig, axes = plt.subplots(
        # nrows=5, sharex=True, figsize=(5, 5.5), height_ratios=[5, 5, 1, 1, 1]
        nrows=4,
        sharex=True,
        # figsize=(5, 5.5),
        # height_ratios=[5, 5, 1, 1, 1],
        figsize=(5, 4),
        height_ratios=[5, 1, 1, 1],
    )

    # # capacity plot
    # ax = axes[0]
    # cap_sum.clip(lower=0).plot.area(
    #     legend="reverse",
    #     color=resource_colors,
    #     linewidth=0,
    #     ax=ax,
    #     ylim=[0, 12000],
    #     ylabel="generator\ncapacity\n(GW)",
    # )
    # ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    # lg = ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", reverse=True)
    # lg.get_frame().set_linewidth(0.0)

    # energy plot
    ax = axes[0]
    dis_sum.clip(lower=0).plot.area(
        legend="reverse",  # False
        color=resource_colors,
        linewidth=0,
        ax=ax,
        ylim=[0, 18000],
        ylabel="electricity\nproduction\n(TWh)",
    )
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    lg = ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", reverse=True)
    lg.get_frame().set_linewidth(0.0)

    # carbon emissions plot
    ax = axes[1]
    carbon.plot(
        ax=ax,
        # ylim=[-0.1, 1.3],
        ylim=[0, 6000],
        color="blue",
        # ylabel="CO2\nemiss.\n(% of\n2028)",
        ylabel="CO₂\nemiss.\n(Mt\nCO₂)",
    )
    # ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:.0%}"))

    # carbon cost plot
    ax = axes[2]
    carbon_cost.plot(
        ax=ax,
        ylim=[0, 200],
        color="blue",
        ylabel="marg.\nCO2\ncost\n($/\ntCO2)",
    )
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("${x:.0f}"))

    # LCOE plot
    ax = axes[3]
    electricity_cost.plot(
        ax=ax,
        legend=False,
        ylim=[0, 150],
        color="blue",
        ylabel="LCOE\n($/\nMWh)",
        xlabel="year",
        xticks=[2028, 2033, 2038, 2043, 2048],
    )
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
    ax.xaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:.0f}"))
    ax.minorticks_off()

    # get shared bounding box dimensions from first figure
    if bbox is None:
        bbox = fig.get_tightbbox()

    fig.savefig(
        # f"{group}/figures/carbon_{co2_level}_all_years.pdf", bbox_inches="tight"
        f"{group}/figures/{scen}_all_years.pdf",
        bbox_inches=bbox,
    )

    # build summary table
    summary.loc[scen, "2028 CO2"] = carbon[2028]
    summary.loc[scen, "2038 CO2"] = carbon[2038]
    summary.loc[scen, "2048 CO2"] = carbon[2048]
    # if 2068 in carbon.index:
    #     summary.loc[scen, "2068 CO2"] = carbon[2068]
    summary.loc[scen, "2028 LCOE"] = electricity_cost.loc[2028, "LCOE"]
    summary.loc[scen, "2038 LCOE"] = electricity_cost.loc[2038, "LCOE"]
    summary.loc[scen, "2048 LCOE"] = electricity_cost.loc[2048, "LCOE"]
    # if 2068 in electricity_cost.index:
    #     summary.loc[scen, "2068 LCOE"] = electricity_cost.loc[2068, "LCOE"]

# rename and sort scenarios
scen_names = {
    "step_0_original": "Original Switch-China",
    "step_9aa_no_ccs_no_h2": "Updated economics and reserves",
    "step_9a_no_ccs": "Add hydrogen options",
    "step_9_tough_day_reserves_10": "Add CCS option",
}
summary = summary.rename(scen_names, axis=0)
idx = list(scen_names.values()) + [
    k for k in summary.index if k not in scen_names.values()
]
summary = summary.loc[idx, :]

summary
# %% go stepwise from original model to mine and from 0 planning reserves to 30%
# (both with $200/tCO2 final point)

group = "out_stepwise"
scenario_lists = {
    "stepwise": {
        "original": "step_0_original",
        "social discount rate": "step_1_discount_rate",
        "ATB 2023 costs and life": "step_2_atb_costs_and_life",
        "allow early retirement": "step_3_early_retire",
        "allow hydrogen": "step_4_h2",
        "allow CCS": "step_5_ccs",
        "10-year intervals": "step_6_sparse_calendar",
        "extend to 2070": "step_7_extended_calendar",
        "planning -> spinning": "step_8_spin_only",
        "10% heat wave reserves": "step_9_tough_day_reserves_10",
    },
    "reserves": {
        "0% heat wave reserves": "step_8_spin_only",
        "10% heat wave reserves": "step_9_tough_day_reserves_10",
        "20% heat wave reserves": "step_10_tough_day_reserves_20",
        "30% heat wave reserves": "step_11_tough_day_reserves_30",
    },
}

for name, scenarios in scenario_lists.items():
    cap_cross = pd.DataFrame()
    dis_cross = pd.DataFrame()
    carbon_cross = pd.DataFrame()
    electricity_cost_cross = pd.DataFrame()
    for scenario_name, scenario_subdir in scenarios.items():
        scenario_dir = os.path.join(group, scenario_subdir)

        cap_sum, dis_sum, carbon_cost, carbon, electricity_cost = read_scenario(
            scenario_dir
        )

        # add to frame, extending index as needed
        for frame, col in [
            (cap_cross, cap_sum),
            (dis_cross, dis_sum),
            (carbon_cross, carbon),
            (electricity_cost_cross, electricity_cost),
        ]:
            col.name = scenario_name

        cap_cross = pd.concat((cap_cross, cap_sum), axis=1)
        dis_cross = pd.concat((dis_cross, dis_sum), axis=1)
        carbon_cross = pd.concat((carbon_cross, carbon), axis=1)
        electricity_cost_cross = pd.concat(
            (electricity_cost_cross, electricity_cost), axis=1
        )

    cap_cross.index.names = ["period", "cat"]
    dis_cross.index.names = ["period", "cat"]

    # filter to 2048
    cap_cross = set_resource_order(
        cap_cross.xs(2048, level="period").fillna(0.0), axis=0
    )
    dis_cross = set_resource_order(
        dis_cross.xs(2048, level="period").fillna(0.0), axis=0
    )
    carbon_cross = carbon_cross.loc[2048, :]
    electricity_cost_cross = electricity_cost_cross.loc[2048, :]

    # Convert to percent of 2028 baseline levels
    # carbon_cross = carbon_cross / 4856000000
    carbon_cross /= 1e6

    # make plots
    fig, axes = plt.subplots(
        nrows=4, sharex=True, figsize=(5, 5), height_ratios=[5, 5, 1, 1]
    )

    # capacity plot
    ax = axes[0]
    x = cap_cross.clip(lower=0).T.plot.bar(
        legend=False,
        color=resource_colors,
        linewidth=0,
        ax=ax,
        ylabel="generator\ncapacity\n(GW)",
        # ylim=[0, 13000],
        stacked=True,
    )
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))

    lg = ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", reverse=True)
    lg.get_frame().set_linewidth(0.0)

    # dispatch plot
    ax = axes[1]
    # leave out slightly negative gas values when plotting
    dis_cross.clip(lower=0).T.plot.bar(
        legend=False,
        color=resource_colors,
        linewidth=0,
        ax=ax,
        ylabel="electricity\nproduction\n(TWh)",
        # ylim=[0, 18000],
        stacked=True,
    )
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))

    # carbon plot
    ax = axes[2]
    carbon_cross.plot(
        ax=ax,
        # ylim=[0, 0.30],
        ylim=[0, 1500],
        linestyle="none",
        marker="_",
        markerfacecolor="blue",
        # ylabel="CO2\nemiss.\n(% of\n2028)",
        ylabel="CO₂\nemiss.\n(Mt\nCO₂)",
    )
    # ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:.0%}"))
    if name == "reserves":
        ax.set_ylim([0, 500])

    # LCOE plot
    ax = axes[3]
    electricity_cost_cross.plot(
        ax=ax,
        ylim=[0, 150],
        linestyle="none",
        marker="_",
        markerfacecolor="blue",
        ylabel="LCOE\n($/\nMWh)",
    )
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
    if name == "reserves":
        labels = [
            x.replace(" reserves", "\nreserves").replace(" heat wave", "\nheat wave")
            for x in scenarios.keys()
        ]
        ax.set_xticklabels(labels)

    else:
        ax.set_xticklabels(scenarios.keys(), rotation=70, ha="right")
    # ax.set_xticklabels(["hello out there great wide world"]*len(scenarios), rotation=70, align="right")

    # # expand bounding box as needed during save to include the legend
    outdir = os.path.join(group, "figures")
    os.makedirs(outdir, exist_ok=True)
    fig.savefig(os.path.join(outdir, f"{name}_{group}.pdf"), bbox_inches="tight")


# %% ################
# for spin_only, reserves_10, reserves_20 or reserves_30, show how these factors
# change:
# evolution of capacity, energy, carbon cost, LCOE over time (graphs above)
# overall system design (graphs above) -- do we prefer different resources as
# we go deep?
# slices of graphs above at the $200/tCO2 point:
# cross-compare 2048 capacity, energy, emission reduction, LCOE between scenarios

# Do all stepwise scenarios with $200/tCO2 price path, and use that for the
# stepwise comparisons and then also reserve comparisons

# %% #############
group = "out_stepwise"
scen = "step_11_tough_day_reserves_30"

gen_info = pd.read_csv("inputs_extended_reserves/gen_info.csv", na_values=".")
gen_info = gen_info.query(
    'gen_energy_source == "Coal" and not gen_tech.str.endswith("_CCS")'
)

# double-check all coal plants have 0.4 as min load
assert all(
    gen_info["gen_min_load_fraction"] == 0.4
), "some gens have unexpected min load"

dw = pd.read_csv(os.path.join(group, scen, "dispatch_wide.csv"), na_values=".")

dw = dw.query('timestamp.str.startswith("205")').set_index("timestamp")
dw = dw.loc[:, gen_info["GENERATION_PROJECT"]]
# only coal plants that are actually used and the hours they are used
dw = dw.loc[dw.sum(axis=1) > 0, dw.sum() > 0]

# mainly on the 2051 days and mainly at constant power
dw.T.describe()
dw.loc["2051-01-04_00:00":, :].describe()

# See whether these are used for reserves and run at min power (40% of commitment)
cap = pd.read_csv(os.path.join(group, scen, "gen_cap.csv"), na_values=".")
cap = cap.query("PERIOD == 2048")
cap = cap.set_index("GENERATION_PROJECT").loc[dw.columns, ["GenCapacity"]].T

(dw.loc["2051-01-04_00:00":, :] / cap.loc["GenCapacity", :]).describe().T.mean()
# hmmm, generally running at full power but only on the difficult days
