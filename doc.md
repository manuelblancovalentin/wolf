
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

#Wolf: A tool for digital flow automation and management.

## 1. Introduction
```bash
TODO
```

## 2. Installation
```bash
TODO
```

## 3. Usage
```bash
TODO
```

#### Commands

- `run`: Run a flow.
- `env`: Manipulates, lists and creates wolf environments, which can be used later for flow recreation.

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

