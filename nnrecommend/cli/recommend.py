import click
import torch
from typing import Container
from nnrecommend.cli.main import Context, main
from nnrecommend.logging import get_logger
from nnrecommend.operation import Finder

@main.command()
@click.pass_context
@click.argument('path', type=click.Path(file_okay=True, dir_okay=False))
@click.option('--item', 'items', default=[], multiple=True, type=str, help="items that you like")
@click.option('--field', 'fields', default=[], multiple=True, type=str, help="fields in item info to check")
def recommend(ctx, path: str, items: Container[str], fields: Container[str]) -> None:
    """
    load a model and get recommendations
    """
    ctx: Context = ctx.obj
    logger = ctx.logger or get_logger(recommend)

    logger.info("reading model file...")
    try:
        with open(path, "rb") as fh:
            data = torch.load(fh)
            model = data["model"]
            idrange = data["idrange"]
            iteminfo = data["iteminfo"]
    except:
        logger.error("failed to load model file")
        return False

    if model is None:
        logger.error("could not load model")
        return

    logger.info(f"loaded model of type {type(model)}")

    finder = Finder(iteminfo, fields)
    itemids = set()
    for item in items:
        r = finder(item)
        logger.info(f"found {r}")
        itemids.add(r.id)

    # TODO: how to add a user to the model?