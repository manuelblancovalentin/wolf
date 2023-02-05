
<span style="color:#ad4ce5;">
<pre style="background-color:#222;">
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░<span style="color:#fff">██╗</span>░░░░░░░<span style="color:#fff">██╗</span>░<span style="color:#fff">█████╗</span>░<span style="color:#fff">██╗</span>░░░░░<span style="color:#fff">███████╗</span>░░░<span style="color:#fff">██████╗</span>░<span style="color:#fff">██╗</span>░░░<span style="color:#fff">██╗███╗</span>░░<span style="color:#fff">██╗</span>░░░░░░░░░░░░
░░░░░░░░░░░░░<span style="color:#fff">██║</span>░░<span style="color:#fff">██╗</span>░░<span style="color:#fff">██║██╔══██╗██║</span>░░░░░<span style="color:#fff">██╔════╝</span>░░░<span style="color:#fff">██╔══██╗██║</span>░░░<span style="color:#fff">██║████╗</span>░<span style="color:#fff">██║</span>░░░░░░░░░░░░
░░░░░░░░░░░░░<span style="color:#fff">╚██╗████╗██╔╝██║</span>░░<span style="color:#fff">██║██║</span>░░░░░<span style="color:#fff">█████╗</span>░░░░░<span style="color:#fff">██████╔╝██║</span>░░░<span style="color:#fff">██║██╔██╗██║</span>░░░░░░░░░░░░
░░░░░░░░░░░░░░<span style="color:#fff">████╔═████║</span>░<span style="color:#fff">██║</span>░░<span style="color:#fff">██║██║</span>░░░░░<span style="color:#fff">██╔══╝</span>░░░░░<span style="color:#fff">██╔══██╗██║</span>░░░<span style="color:#fff">██║██║╚████║</span>░░░░░░░░░░░░
░░░░░░░░░░░░░░<span style="color:#fff">╚██╔╝</span>░<span style="color:#fff">╚██╔╝</span>░<span style="color:#fff">╚█████╔╝███████╗██║</span>░░░░░<span style="color:#fff">██╗██║</span>░░<span style="color:#fff">██║╚██████╔╝██║</span>░<span style="color:#fff">╚███║</span>░░░░░░░░░░░░
░░░░░░░░░░░░░░░<span style="color:#fff">╚═╝</span>░░░<span style="color:#fff">╚═╝</span>░░░<span style="color:#fff">╚════╝</span>░<span style="color:#fff">╚══════╝╚═╝</span>░░░░░<span style="color:#fff">╚═╝╚═╝</span>░░<span style="color:#fff">╚═╝</span>░<span style="color:#fff">╚═════╝</span>░<span style="color:#fff">╚═╝</span>░░<span style="color:#fff">╚══╝</span>░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
</pre>
</span>

# WOLF: A tool for digital flow automation and management.

![Algo](imgs/road_sign.png)
## 1. Introduction
```bash
TODO
```

## 2. Installation

#### 2.1. Cloning wolf 
The first thing to do is to clone this repo into a local folder in your machine. If multiple users are expected to use wolf, I would suggest cloning this into an area such as `/asic/cad/wolf`. If you don't have permission to create a directory at `/` then just clone it into your home folder. The following code assumes the second option:
```bash
cd $HOME
git clone git@github.com:manuelblancovalentin/wolf.git
```

Wolf has one single dependency (ignoring python) which is `shyaml` (more info [here](https://pypi.org/project/shyaml/)). Quoting their webpage, shyaml is a: 
>Simple script that allow read access to YAML files through command line.

#### 2.2 (Optional) - shyaml dependency
Wolf basically needs this because at a specific point it requires to read some yaml file from the configuration of the flow (looking for the RTL sources). 

First of all, let's check if shyaml is already there in your system. To do so, execute:

```bash
which shyaml
```

If the previous command returns a valid path, something like `/home/manuelbv/.local/bin/shyaml`, then you can skip this step (2.2) and go straight to 2.3. If not, proceed with installation of shyaml.

To install shyaml (make sure you install it for python3, not python2), you can execute something like the following command (although we recommend going to their [webpage](https://pypi.org/project/shyaml/) and following their instructions):

```bash
pip3 install shyaml
```

Once shyaml has been locally installed, you can make sure it works by trying to call it by executing `shyaml`. Hopefully, you should get an error message like this:

```bash
$> shyaml
Error: Bad number of arguments.
Usage:

    shyaml {-h|--help}
    shyaml {-V|--version}
    shyaml [-y|--yaml] [-q|--quiet] ACTION KEY [DEFAULT]
```

If this is the case, then that means shyaml has been properly installed. If not, you'll have to come back to `shyaml` source page and make sure you are going through the installation procedure correctly. 

In case you did install it correctly and you are still struggling with making it work, there's a possibility that the location of shyaml is simply not in your path. Let's imagine that your cadadmin actually installed shyaml on their side, and they give you the location of it in your system (they can achieve this by running `which shyaml` on their side). In such case, the only thing we need to do is to add that path to your `.bashrc` file. Remember this path (let's call it `SHYAML_PATH`), cause we will use it in the next step.

#### 2.3. Adding wolf (and shyaml) to your path

So now let's modify your `.bashrc` to add both wolf and shyaml (the later, only in case shyaml is not working properly). Open your bashrc file (located at your home folder, under `/home/$USER/.bashrc`) with your preferred editor, scroll all the way down and add the following lines. **Please, note that you'll have to modify the variable WOLF_PATH to point to your local installation of wolf, that is, the directory where you cloned the wolf repo**:

```bash
WOLF_PATH="/home/$USER/wolf"

# >>> wolf initialize >>>
if [ -f "${WOLF_PATH}/bin/wolf.init.sh" ]; then
    . "${WOLF_PATH}/bin/wolf.init.sh"
else
    # Add wolf to path
	export PATH="$WOLF_PATH":$PATH
fi
# <<< wolf initialize <<<
```

(Optional): If you had to go through step 2.2 to setup shyaml, then we will also need to add SHYAML to your path. To do so, apart from the previous block, add the following block to your `.bashrc` file, after wolf initialize. **Please, note that we removed the `shyaml` part of the path, cause we want to add the PATH where the binary for shyaml is located, and not the binary itself**:

```bash
# Add shyaml to path
# NOTE (!!!): If the output of "which shyaml" is 
#  "/home/manuelbv/.local/bin/shyaml", then the path to 
#  be added to PATH variable is "/home/manuelbv/.local/bin/".
SHYAML_PATH="/home/manuelbv/.local/bin"
export PATH="$SHYAML_PATH":$PATH
```

After all of these changes have been applied, you will need to either restart your console (if you are using ssh, just log out and log in back again) or source your `.bashrc` file. I'd recommend the first one. If you are using VNC, you can simply just open either a new tab or a new terminal. 

To make sure wolf is correctly installed, run `wolf` and make sure you get an error message similar to the following:

```bash
$> wolf
 [ERROR] - Invalid command passed to wolf. Wolf requires at least 1 command to be executed. Valid commands are: "run", "env"
```

🎉 If you see the previous message... congratulations! You successfully installed wolf in your system.

## 3. Usage
```bash
TODO
```

#### Commands

- `run`: Run a flow.
- `env`: Manipulates, lists and creates wolf environments, which can be used later for flow recreation.
- `track`: Display active wolf processes.

### Wolf.run

Options:
```bash
Main arguments taken wolf.run:
        -h, --help              Invokes this dialog.

Flow behavior arguments:
        -c, --clean             If set to true, the flow will be run from scratch, ignoring any previous runs, in a new folder.
                                    DEFAULT: false
        -y, --yes               If this flag is present, the script will skip user confirmation at its end, and proceed running the flow.
                                    DEFAULT: false
        -t, --runtag            Manually sets the runtag to a specific value, instead of automatically setting it according to previous runs.
                                    DEFAULT: Obtained automatically by script.
Project-specific arguments:
        -p, --process           Specification of process to be used while running the flow. Must be one of "TSCM65", "GF22"
                                    DEFAULT: TSCM65
        -d, --design            Specification of the design to be synthesized. Must be one of "tdsp_core"
                                    DEFAULT: tdsp_core
        -f, --conf              Specify the full path of the template yaml file used to generate the final setup final that will be passed to flowtool.
                                    DEFAULT:

```




### STEPS:

0. Remove previous process (no user confirmation)
```shell
wolf process remove -y --name tsmc65
```

1. Create a process (library/ip)
```shell
wolf process create --name tsmc65
```

2. Add metal stack to it
```shell
wolf process -n tsmc65 --add-stack
```






### Wolf.env

#### Create environment 

```bash
foo@bar:~$ wolf env create <NAME>

 ######################################################################################################
 Wolf environments: 
 -------------------------------------------------- 
 test [/tmp/wolf/.envs/test]
 ######################################################################################################
```

#### List environments

```bash
foo@bar:~$ wolf env list

 ######################################################################################################
 Wolf environments: 
 -------------------------------------------------- 
 test [/tmp/wolf/.envs/test]
 ######################################################################################################
```




```
wolf update bucket
```

```
wolf update
```

## Example for AI in pixel
First create an environment
```bash
foo@bar:~$ wolf create -n pixelAI
```

Now activate the environment and setup some variables
```bash
foo@bar:~$ wolf activate pixelAI
|wolf:pixelAI| foo@bar:~$ DESIGN_NAME="pixelArray_full_readout"
```

Now update the bucket of source files to point to the general source script used for all the designs in the FLORA project (point to `/asic/projects/FNAL/xray_imaging/manuelbv/src/inputs/env/FLORA_env.csh`):
```bash
|wolf:pixelAI| foo@bar:~$ wolf update --bucket


    ┌──────────────────────────────────────────────Please choose a file────────────────────────────────────────────────┐
    │ Directories                                             Files                                                    │  
    │ ┌──────────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────┐ │  
    │ │.                                                     ││FLORA_env.csh                                         │ │  
    │ │..                                                    ││FLORA_src.yaml                                        │ │  
    │ │                                                      ││                                                      │ │  
    │ │                                                      ││                                                      │ │  
    │ └───────────────────────────────────────────────50%────┘└───────────────────────────────────────────────12%────┘ │  
    │ ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────┐ │  
    │ │/asic/projects/FNAL/xray_imaging/manuelbv/src/inputs/env/FLORA_env.csh                                        │ │  
    │ └──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │  
    ├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤  
    │                                       <  OK  >                    <Cancel>                                       │  
    └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘  
```

Now update the wolf environment to save the changes. And reload the environment.

```bash
|wolf:pixelAI| foo@bar:~$ wolf update
|wolf:pixelAI| foo@bar:~$ wolf env reload
```

## Ip-manager
What is this used for?
```
TODO
```

#### Install a library/process
```
TODO
```
Define corners, opconds, voltages,...

- Device map
- Objectmap
- Layermap path
- Techfile path
- qrcTechfile path
- Voltages/Temp ranges


#### PDK/Digital libs
```
TODO
```

#### Query information about the library
LEFS
```
TODO
```
GDS
```
TODO
```
SPICE
```
TODO
```
VERILOG
```
TODO
```

## Wizard
What can you setup using the wizard?

#### RTL/inputs
Setup and point to the code required for the flow

#### Technology/Process
Pick process to be used among installed ips 

- TSMC 28nm
- TSMC 65nm
- GF 22nm
- etc.

#### MMMC config
- Library sets
- Op conds
- Timing conditions
- RC corners
- Delay corners
- Constraint modes
- Analysis views

#### Cells
 - Don't use. A window in the command line line below, where the user can pick which cells not to use.
```bash

    ┌────────────────────────────────────────────── Choose cells to use  ────────────────────────────────────────────────┐
    │                                                                                                                    │
    │────────────────────────────────────────────────────────────────────────────────────────────────────────────────────│
    │ [x] CKND1                                                                                                          │  
    │ [x] CKND2                                                                                                          │ 
    │ [x] CKND4                                                                                                          │ 
    │ [ ] CFDN1                                                                                                          │ 
    │ [ ] CFDN2                                                                                                          │
    │ [ ] ...                                                                                                            │
```


#### Calibre DRC/LVS
- Point to custom LVS rulefiles to be added for nmLVS
  - setup.yaml: `user_lvs_rulefiles` 
- Point to custom DRC rulefiles to be added for DRC
  - setup.yaml: `user_drc_rulefiles` 


