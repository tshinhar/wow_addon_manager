this is a very simple addon manager tool for World of Warcraft

How to use it: 

edit `addons_path` in the settings to the folder where your mods should
be extracted to.

add the github URLs of the mods you want to have installed
(note that you need to give them a name, you can name them whatever you
want, this is for internal use only)
run the update, which will download and install all addons
from the repositories listed in `addons.json`

notes:
the manager itself gives you the option to change settings and 
add/remove repositories, but you can also do it by manually editing the
json files (make sure not to break them, invalid json will cause a crash
on start).
this project is in very early stages and still missing a lot of
functionality and features, it is not production ready in any way, 
use at your own risk.
