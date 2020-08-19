from collections import OrderedDict

from couler.core import pyfunc, states
from couler.core.templates import OutputArtifact, Step


def update_step(func_name, args, step_name, caller_line):
    if states.workflow.dag_mode_enabled():
        step_name = _update_dag_tasks(
            func_name,
            states._dag_caller_line,
            states._upstream_dag_task,
            args,
            step_name=step_name,
        )
        states._upstream_dag_task = [step_name]
    else:
        if states._run_concurrent_lock:
            step_name = _update_steps(
                "concurrent_func_name",
                states._concurrent_func_line,
                args,
                func_name,
            )
        else:
            step_name = _update_steps(func_name, caller_line, args)

    return step_name


def _update_dag_tasks(
    function_name,
    caller_line,
    dependencies,
    args=None,
    template_name=None,
    step_name=None,
):
    """
    A task in DAG of Argo YAML contains name, related template and parameters.
    Here we insert a single task into the global tasks.
    """
    if step_name is None:
        function_id = pyfunc.invocation_name(function_name, caller_line)
    else:
        function_id = step_name

    task_template = states.workflow.get_dag_task(function_id)
    if task_template is None:
        task_template = OrderedDict({"name": function_id})

        if dependencies is not None and isinstance(dependencies, list):
            if "dependencies" in task_template:
                task_template["dependencies"].extend(dependencies)
            else:
                task_template["dependencies"] = dependencies

        if template_name is None:
            task_template["template"] = function_name
        else:
            task_template["template"] = template_name

        # configure the args
        if args is not None:
            parameters, artifacts = _get_params_and_artifacts_from_args(
                args, function_name, prefix="tasks"
            )

            if len(parameters) > 0:
                task_template["arguments"] = OrderedDict()
                task_template["arguments"]["parameters"] = parameters

            if len(artifacts) > 0:
                if "arguments" not in task_template:
                    task_template["arguments"] = OrderedDict()

                task_template["arguments"]["artifacts"] = artifacts

    else:
        # step exist on the dag, thus, we update its dependency
        if dependencies is not None:
            if "dependencies" in task_template:
                task_template["dependencies"].append(dependencies)
            else:
                task_template["dependencies"] = [dependencies]

    states.workflow.update_dag_task(function_id, task_template)

    # return the current task name
    return function_id


def _update_steps(function_name, caller_line, args=None, template_name=None):
    """
    A step in Argo YAML contains name, related template and parameters.
    Here we insert a single step into the global steps.
    """
    function_id = pyfunc.invocation_name(function_name, caller_line)

    # Update `steps` only if needed
    if states._update_steps_lock:
        name = function_id
        if states._run_concurrent_lock:
            _id = pyfunc.invocation_name(template_name, caller_line)
            name = "%s-%s" % (_id, states._concurrent_func_id)
            if states._sub_steps is not None:
                states._concurrent_func_id = states._concurrent_func_id + 1

        t_name = function_name if template_name is None else template_name
        step = Step(name=name, template=t_name)

        if states._when_prefix is not None:
            step.when = states._when_prefix

        if args is not None:
            parameters, artifacts = _get_params_and_artifacts_from_args(
                args,
                template_name
                if states._run_concurrent_lock
                else function_name,
                prefix="steps",
            )

            if len(parameters) > 0:
                step.arguments = OrderedDict()
                step.arguments["parameters"] = parameters

            if len(artifacts) > 0:
                if step.arguments is None:
                    step.arguments = OrderedDict()
                step.arguments["artifacts"] = artifacts

        if states._condition_id is not None:
            function_id = states._condition_id

        if states._while_lock:
            if function_id in states._while_steps:
                states._while_steps.get(function_id).append(step.to_dict())
            else:
                states._while_steps[function_id] = [step.to_dict()]
        else:
            if states._sub_steps is not None:
                if function_id in states._sub_steps:
                    states._sub_steps.get(function_id).append(step.to_dict())
                else:
                    states._sub_steps[function_id] = [step.to_dict()]
            elif states._exit_handler_enable is True:
                if function_id in states.workflow.exit_handler_step:
                    states.workflow.exit_handler_step.get(function_id).append(
                        step.to_dict()
                    )
                else:
                    states.workflow.exit_handler_step[function_id] = [
                        step.to_dict()
                    ]
            else:
                states.workflow.add_step(function_id, step)

        return step.name
    else:
        return function_id


def _get_params_and_artifacts_from_args(args, input_param_name, prefix):
    parameters = []
    artifacts = []
    if not isinstance(args, list):
        args = [args]
    i = 0
    for values in args:
        values = pyfunc.parse_argo_output(values, prefix)
        if isinstance(values, list):
            for value in values:
                parameters.append(
                    {
                        "name": pyfunc.input_parameter_name(
                            input_param_name, i
                        ),
                        "value": value,
                    }
                )
                i += 1
        else:
            if isinstance(values, OutputArtifact):
                artifacts.append(
                    {
                        "name": pyfunc.input_parameter_name(
                            input_param_name, i
                        ),
                        "from": values,
                    }
                )
            else:
                parameters.append(
                    {
                        "name": pyfunc.input_parameter_name(
                            input_param_name, i
                        ),
                        "value": values,
                    }
                )
            i += 1
    return parameters, artifacts