import os
import re
import pandas as pd
import typer

app = typer.Typer()


@app.command()
def extract_edges(log_dir):
    files = os.listdir(log_dir)
    re_edge_file = re.compile(r"[a-zA-Z]+Edge\.tsv$")

    def extract_edge_types(raw):
        cols = ["srcNodeType", "rel", "dstNodeType"]
        _df = raw[cols]
        _df = _df.drop_duplicates().dropna(inplace=False)
        for _, row in _df.iterrows():
            sub = raw[
                (raw["srcNodeType"] == row.iloc[0])
                & (raw["dstNodeType"] == row.iloc[2])
                & (raw["rel"] == row.iloc[1])
            ]
            sub = sub.drop(columns=cols, inplace=False)
            sub.to_csv(
                os.path.join(log_dir, "_".join(row) + "_Edge.tsv"),
                sep="\t",
                index=False,
            )

    for file in files:
        if re_edge_file.match(file):
            file_path = os.path.join(log_dir, file)
            df = pd.read_csv(file_path, sep="\t", header=0)
            extract_edge_types(df)
            os.remove(file_path)


if __name__ == "__main__":
    app()
