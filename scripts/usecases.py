import datetime
import os
import time

import dask
import dask.array as da
import joblib
import numpy as np
import xarray as xr
from dask import delayed
from sklearn.datasets import make_classification
from sklearn.model_selection import GridSearchCV
from sklearn.svm import SVC


def bench_pandas_groupby(days=1, freq="1s", partition_freq="1H"):
    """
    https://examples.dask.org/dataframe.html
    """
    start = datetime.datetime(year=2020, month=1, day=1)
    end = start + datetime.timedelta(days=days)

    df = dask.datasets.timeseries(start=start, end=end, seed=0,
                                  freq=freq, partition_freq=partition_freq)
    m = df.groupby("name")["x"].mean().sum()
    s = df[(df["x"] > 0) & (df["y"] < 0)]["x"].resample("2S").mean().sum()
    return m + s


def bench_pandas_join(days=1, freq="1s", partition_freq="2H"):
    start = datetime.datetime(year=2020, month=1, day=1)
    end = start + datetime.timedelta(days=days)

    df = dask.datasets.timeseries(start=start, end=end, seed=0,
                                  freq=freq,
                                  partition_freq=partition_freq,
                                  dtypes={"value": float, "name": str, "id": int},
                                  id_lam=100)
    merged = df.merge(df, on="id", how="inner")
    return merged["value_x"].sum()


def bench_bag(count):
    """
    https://examples.dask.org/bag.html
    """
    b = dask.datasets.make_people(seed=0, npartitions=10, records_per_partition=count)
    res = b.filter(lambda record: record["age"] > 30) \
        .map(lambda record: record["occupation"]) \
        .frequencies(sort=True) \
        .topk(10, key=1) \
        .pluck(1) \
        .sum()
    return res


@delayed
def do_something(x):
    return x * 10


@delayed
def sleep(delay):
    time.sleep(delay)
    return delay


@delayed
def merge(*args):
    return sum(args)


def bench_merge(count=1000):
    xs = [do_something(x) for x in range(count)]
    result = merge(*xs)
    return result


def bench_merge_slow(count=1000, delay=0.5):
    xs = [sleep(delay) for _ in range(count)]
    result = merge(*xs)
    return result


def bench_numpy(size=25000):
    """
    https://examples.dask.org/array.html
    """
    da.random.seed(0)
    x = da.random.random((size, size), chunks=(1000, 1000))
    y = x + x.T
    return np.sum(y[::2, size / 2:].mean(axis=1))


@delayed
def add(x, y):
    return x + y


def bench_tree(exp=10):
    """
    https://examples.dask.org/delayed.html#Custom-computation:-Tree-summation
    """
    L = list(range(2 ** exp))
    while len(L) > 1:
        new_L = []
        for i in range(0, len(L), 2):
            lazy = add(L[i], L[i + 1])  # add neighbors
            new_L.append(lazy)
        L = new_L                       # swap old list for new

    return L


def bench_xarray(chunk_size=5):
    """
    https://examples.dask.org/xarray.html
    """
    ds = xr.tutorial.open_dataset("air_temperature",
                                  chunks={"lat": chunk_size, "lon": chunk_size, "time": -1})
    da = ds["air"]
    da2 = da.groupby("time.month").mean("time")
    da3 = da - da2
    return da3.sum()


def bench_scikit():
    X, y = make_classification(n_samples=1000, random_state=0)
    param_grid = {"C": [0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
                  "kernel": ["rbf", "poly", "sigmoid"],
                  "shrinking": [True, False]}

    grid_search = GridSearchCV(SVC(gamma="auto", random_state=0, probability=True),
                               param_grid=param_grid,
                               return_train_score=False,
                               iid=True,
                               cv=3,
                               n_jobs=-1)
    with joblib.parallel_backend("dask"):
        grid_search.fit(X, y)
    return np.sum(grid_search.predict(X)[:5])


if __name__ == "__main__":
    import networkx

    os.makedirs("graphs", exist_ok=True)
    usecases = {
        "pandas-groupby-1-1T-1H": bench_pandas_groupby(1, "1T", "1H"),
        "pandas-groupby-1-1T-8H": bench_pandas_groupby(1, "1T", "8H"),
        "pandas-join-1-1T-1H": bench_pandas_join(1, "1T", "1H"),
        "pandas-join-1-1T-8H": bench_pandas_join(1, "1T", "8H"),
        "bag-1000": bench_bag(1000),
        "merge-1000": bench_merge(1000),
        "numpy-2000": bench_numpy(2000),
        "tree-8": bench_tree(8),
        "xarray-20": bench_xarray(20)
    }
    for (name, graph) in usecases.items():
        dot_filename = f"graphs/{name}"
        dask.visualize(graph, format="dot", filename=dot_filename)
        dask.visualize(graph, filename=f"graphs/{name}.svg")
        g = networkx.drawing.nx_agraph.read_dot(f"{dot_filename}.dot")
        print(f"""
{name}: {len(g.nodes)} vertices, {len(g.edges)} edges, longest path: {networkx.dag_longest_path_length(g)}
""".strip())
