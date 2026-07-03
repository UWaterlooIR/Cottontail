load("@rules_cc//cc:defs.bzl", "cc_test")

cc_test(
    name = "tests",
    srcs = glob(["**/*.cc"], exclude = [
        "hazel.cc",
        "jsonl.cc",
        "jsonl_cli.cc",
        "jsonl_server.cc",
        "optimizer.cc",
    ]) + glob(["**/*.h"]),
    deps = [
        "//src:cottontail",
        "@googletest//:gtest_main",
    ],
    linkopts = [
        "-lz",
        "-pthread",
    ],
    data = [
        "books.json",
        "ranking.txt",
        "sonnet0.txt",
        "sonnet1.txt",
        "sonnet2.txt",
        "test.tsv",
        "test0.txt",
        "test.qrels",
    ],
)

cc_test(
    name = "hazel_test",
    size = "small",
    srcs = [
        "hazel.cc",
    ],
    deps = [
        "//src:cottontail",
        "@googletest//:gtest_main",
    ],
    linkopts = [
        "-lz",
        "-pthread",
    ],
)

cc_test(
    name = "optimizer_test",
    size = "small",
    srcs = [
        "optimizer.cc",
    ],
    deps = [
        "//src:cottontail",
        "@googletest//:gtest_main",
    ],
    linkopts = [
        "-lz",
        "-pthread",
    ],
)

cc_test(
    name = "jsonl_test",
    size = "small",
    srcs = [
        "jsonl.cc",
        "jsonl_cli.cc",
    ],
    data = [
        "jsonl/bad/malformed.jsonl",
        "jsonl/gz/sample.jsonl.gz",
        "jsonl/plain/sample.jsonl",
        "//apps:cottontail-jsonl-index",
        "//apps:cottontail-jsonl-query",
    ],
    deps = [
        "//apps:jsonl_core",
        "//src:cottontail",
        "@googletest//:gtest_main",
    ],
    linkopts = [
        "-lz",
        "-pthread",
    ],
)

cc_test(
    name = "jsonl_server_test",
    size = "small",
    srcs = [
        "jsonl_server.cc",
    ],
    data = [
        "jsonl/plain/sample.jsonl",
        "//apps:cottontail-jsonl-index",
        "//apps:cottontail-jsonl-server",
    ],
    deps = [
        "//src:cottontail",
        "@cpp-httplib//:httplib",
        "@googletest//:gtest_main",
    ],
    linkopts = [
        "-lz",
        "-pthread",
    ],
)
