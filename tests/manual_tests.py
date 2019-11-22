from dataclasses import fields
from functools import wraps
from time import perf_counter, process_time
from pprint import pprint


from bson import ObjectId, Decimal128

import models

def profile(func):
  @wraps(func)
  async def decorator(*args, **kwargs):
    counter, time = perf_counter(), process_time()
    await func(*args, **kwargs)
    print({"pref_counter": (perf_counter() - counter), "process_time": (process_time() - time)})


  return decorator

def task1():
  task1 = models.Task("Task 1", "This is Task 1's description")
  print(task1)
  print(task1.to_json())
  print()

def task2():
  task2 = models.Task("Task 2", "This is Task 2's description", "Tag1, Tag2", path = "/garito", id_ = ObjectId())
  print(task2)
  print(task2.to_dict())
  print(task2.to_json())
  print(task2.to_plain_dict())
  print(task2.get_url())
  print(task2.json_schema())
  print(task2._composition())
  print()

def task3():
  data = {"name": "Task 3", "reward": 100.50, "_id": str(ObjectId())}
  task3 = models.Task.from_dict(data)
  print(data)
  print(task3)
  print(task3.reward)
  print(type(task3.reward))
  from json import dumps
  print(dumps(models.Task.json_schema(), indent = 2))
  # pprint(fields(models.Task), indent = 2)
  print()
  task3_1 = models.Task(name = "Task 3.1", reward = Decimal128("100.50"))
  print(task3_1)
  print(task3_1.reward)
  print(type(task3_1.reward))
  print(task3_1.to_json())

def task4():
  oid = ObjectId()
  data = f'{{"name": "Task 4", "description": "This is Task 4\'s description", "tags": "Tag1, Tag2", "path": "garito", "id_": "{ oid }"}}'
  task4 = models.Task.from_json(data)
  print(data)
  print(task4)
  print()

async def crud(table):
  task5 = models.Task(name = "Task 5", description = "This is Task 5's description", tags = "Tag1, Tag2", path = "/garito", _table = table)
  url = f"{task5.path}/{task5.slug}"
  print("defined")
  print(task5)
  print()

  await task5.create()
  print("created")
  print(task5)
  print(await models.Task.get(table, url = url))
  print()

  await task5.update(**{"description": "This is Task 5's description. Edited", "tags": "Tag1, Tag2, Tag3"})
  print("updated")
  print(task5)
  print(await models.Task.get(table, url = url))
  print()

  await task5.finish()
  print("finished")
  print(task5)
  print(await models.Task.get(table, url = url))
  print()

  await task5.delete()
  print("deleted")
  print(task5)
  print(await models.Task.get(table, url = url))
  print()

async def setup_recursive_tasks(table):
  task1111 = models.Task("Task 1 1 1 1", "This is Task 1 1 1 1's description", path = "/task-1/task-1-1/task-1-1-1")
  task1111._table = table
  task111 = models.Task("Task 1 1 1", "This is Task 1 1 1's description", path = "/task-1/task-1-1", tasks = [task1111.slug])
  task111._table = table
  task11 = models.Task("Task 1 1", "This is Task 1 1's description", path = "/task-1", tasks = [task111.slug])
  task11._table = table
  task1 = models.Task("Task 1", "This is Task 1's description", path = "/", tasks = [task11.slug])
  task1._table = table
  task = models.Task("Task", "This is Task's description", path = "", tasks = [task1.slug])
  task._table = table

  await task.create()
  await task1.create()
  await task11.create()
  await task111.create()
  await task1111.create()
  print(task)
  print(task1)
  print(task11)
  print(task111)
  print(task1111)
  print()
  return [task, task1, task11, task111, task1111]

async def remove_recursive_tasks(tasks):
  for task in tasks:
    await task.delete(models)

async def ancestors(table):
  tasks = await setup_recursive_tasks(table)

  pprint(await tasks[-1].ancestors(models))
  print()

  await remove_recursive_tasks(tasks)

async def group(table):
  group = await models.Group.get(table, url = "/")
  print(group)

async def user(table):
  garito = await models.User.get(table, url = "/garito")
  print(garito)

async def task_ancestors(table):
  task = await models.Task.get(table, url = "/garito/task-1/task-1-1/task-1-1-1/task-1-1-1-1")

  for ancestor in await task.ancestors(models):
    print(ancestor)
    print()

  print(task)
  print()

@profile
async def task_children(table):
  # group = await models.Group.get(table, url = "/")
  # user = await models.User.get(table, slug = "garito")
  task = await models.Task.get(table, url = "/garito/task-1")
  # print(group)
  # print()
  # print(user)
  # print()
  print(task)
  print()

  # group_children = await group.children(models)
  # pprint(group_children)
  # print()

  # user_children = await user.children(models)
  # pprint(user_children)
  # print()

  task_children = await task.children(models)
  pprint(task_children)
  print()

async def user_create_task(table):
  user = models.User("Garito", "garito@gmail.com", path = "/")
  user._table = table
  await user.create()
  print(user)
  print()

  task = models.Task("Task", "This is Task's description")
  print(task)
  print()
  await user.create_child(task, models)
  print(user)
  print(task)
  print()
  print(await models.User.get(table, slug = "garito"))
  print(await models.Task.get(table, url = "/garito/task"))

  await user.delete(models)
  await task.delete(models)

async def task_delete(table):
  tasks = await setup_recursive_tasks(table)

  await tasks[0].delete(models)

async def task_update(table):
  tasks = await setup_recursive_tasks(table)

  await tasks[1].update(models, name = "Task 1. Edited")
  print()
  pprint(tasks)
  pprint(await table.find({"type": "Task"}).to_list(None))
  print()

  await tasks[0].delete(models)
