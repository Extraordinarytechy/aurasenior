"""YAML loader that keeps CloudFormation intrinsic tags (!Ref, !Sub, !GetAtt, !If ...) as plain dicts."""
import yaml


class CfnLoader(yaml.SafeLoader):
    pass


def _construct(loader, tag_suffix, node):
    name = "Fn::" + tag_suffix if tag_suffix not in ("Ref", "Condition") else tag_suffix
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        if tag_suffix == "GetAtt":
            value = value.split(".", 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {name: value}


CfnLoader.add_multi_constructor("!", _construct)


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=CfnLoader)
