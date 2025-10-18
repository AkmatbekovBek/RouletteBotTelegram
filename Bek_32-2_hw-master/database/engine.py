# from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
# from sqlalchemy.orm import sessionmaker
# from config import DB_URL
#
# # ЯВНО ОТКЛЮЧАЕМ ЛОГИРОВАНИЕ
# engine = create_async_engine(
#     DB_URL,
#     echo=False,  # основное отключение
#     echo_pool=False,  # отключаем логи пула
#     future=True,
#     # Дополнительные параметры для отключения логов
#     hide_parameters=True  # скрывает параметры запросов
# )
#
# async_session = sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False
# )