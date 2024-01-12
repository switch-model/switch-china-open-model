# Problem: original model didn't specify a reserve rule and Switch
# let that slide. Now we want to apply a rule for some models, but
# not when running the original one. So we can't put the rule flag
# in options.txt, but it's a hassle to remember to set it for every
# scenario that uses the new reserve framework. So we allow adding
# this module instead to have the same effect.

# Makes NREL "3+5" spinning reserves rule the default when using
# switch_model.balancing.operating_reserves.spinning_reserves
# Adding this module to modules.txt is equivalent to specifying
# --spinning-requirement-rule "3+5" on the command line. However,
# using a module for it is useful because it turns on the behavior
# for certain inputs directories without changing the behavior of
# others (which may be to use no rule at all) and without requiring
# any command line arguments.


def define_arguments(argparser):
    argparser.set_defaults(spinning_requirement_rule="3+5")
