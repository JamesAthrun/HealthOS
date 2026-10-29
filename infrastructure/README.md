# Infrastructure

本目录用于保存不含 Secret 的部署、备份、恢复和可观测性配置。

生产配置必须保证 PostgreSQL 与对象存储管理端口不暴露公网，并将 Secret 从版本控制和镜像中排除。
