import trimesh

mesh = trimesh.load("part.stl", force="mesh")
mesh.process(validate=True)
with open("summary.txt", "w") as fh:
    fh.write(f"{float(mesh.volume):.6f}, {float(mesh.area):.6f}\n")
