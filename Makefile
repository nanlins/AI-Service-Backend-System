.PHONY: install up down dev worker migrate revision test testdb lint fmt init-data loadtest

install:            ## 安装依赖（含开发依赖）
	pip install -e ".[dev]"

up:                 ## 一条命令启动完整环境
	docker compose up --build -d

down:
	docker compose down

dev:                ## 本地启动 API（需先启动 PG/Redis/RabbitMQ）
	uvicorn app.main:app --reload

worker:             ## 本地启动任务 Worker
	python -m app.worker

migrate:            ## 应用数据库迁移
	alembic upgrade head

revision:           ## 生成新迁移：make revision m="msg"
	alembic revision --autogenerate -m "$(m)"

testdb:             ## 创建/重建测试数据库
	python scripts/create_test_db.py

test:               ## 一条命令运行测试
	pytest

lint:
	ruff check .

fmt:
	ruff format .

init-data:          ## 初始化演示数据
	python scripts/init_data.py

loadtest:           ## 简单压测
	python scripts/load_test.py
