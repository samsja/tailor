from typing import List, Optional, Union

import torch
from torch.fx import GraphModule, Tracer
from torch.fx.passes.shape_prop import ShapeProp as ShapeInterpreter

from ._symbolic_trace import symbolic_trace_with_custom_tracer
from .freezer import FreezerMixin
from .rewriter import SublayerRewriter
from .tracer import ModuleNodeTracer
from .utils import (count_module_parameters, get_named_modules_mapping,
                    get_named_parameters_mapping)
from .visualizer import VisualizerMixin


class Tailor(VisualizerMixin, FreezerMixin, SublayerRewriter):
    def __init__(self, model: torch.nn.Module, tracer: Optional[Tracer] = None):
        super().__init__()
        self._model = model
        self._tracer = tracer if tracer else ModuleNodeTracer()
        self.visualizer = VisualizerMixin()

    def trace(self) -> GraphModule:
        return symbolic_trace_with_custom_tracer(root=self._model, tracer=self._tracer)

    def _interpret(
        self,
        input_shape: Union[list, tuple],
        skip_call_function: bool = True,
    ) -> List[dict]:
        rv = []
        input_ = torch.randn(input_shape)
        name_module_mapping = get_named_modules_mapping(self._model)
        name_params_mapping = get_named_parameters_mapping(self._model)
        traced = self.trace()
        self.shape_interpreter = ShapeInterpreter(traced)
        self.shape_interpreter.propagate(input_)
        for node in traced.graph.nodes:
            if skip_call_function and node.op == 'call_function':
                continue
            module_name = self._tracer.get_module_name_by_node(node)
            if module_name and name_module_mapping.get(module_name):
                item = {}
                current_module = name_module_mapping[module_name]
                current_params = name_params_mapping.get(module_name)
                num_params = count_module_parameters(current_module)
                trainable = (
                    True
                    if num_params > 0
                    and current_params is not None
                    and current_params.requires_grad
                    else False
                )
                item['name'] = module_name
                item['num_params'] = num_params
                item['trainable'] = trainable
                tensor_meta = node.meta.get('tensor_meta')
                # if node.op is `call_function`, do not have tensor meta.
                if tensor_meta and isinstance(tensor_meta, dict):
                    item['dtype'] = tensor_meta.dtype
                    item['shape'] = list(tensor_meta.shape)
                elif isinstance(tensor_meta, torch.fx.passes.shape_prop.TensorMetadata):
                    item['dtype'] = tensor_meta.dtype
                    item['shape'] = list(tensor_meta.shape)
                else:
                    item['dtype'] = 'unknown'
                    item['shape'] = 'unknown'
                rv.append(item)
        return rv

    @property
    def model(self):
        return self._model
