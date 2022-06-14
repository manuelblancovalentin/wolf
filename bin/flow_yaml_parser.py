import sys
import yaml

def recursive_key_search(substruct, cum="", current_flows=[]):
    subout = tuple()
    if isinstance(substruct, dict):
        for (k, v) in substruct.items():
            if k != "steps":
                if cum == "":
                    for j in current_flows:
                        if k.startswith(j):
                            # Go straight to values
                            cumtmp = f"{k}"
                            subout += (cumtmp,)
                            #print(f"dict: {cumtmp}")
                            subout += recursive_key_search(v, cum=cumtmp)
                else:
                    # Go straight to values
                    cumtmp = f"{cum}.{k}"
                    subout += (cumtmp,)
                    #print(f"dict: {cumtmp}")
                    subout += recursive_key_search(v, cum=cumtmp)
                        
            else:
                subout += recursive_key_search(v, cum=f"{cum}")

    elif isinstance(substruct,list):
        for v in substruct:
            subout += recursive_key_search(v, cum=f"{cum}")
    return subout

def main(args):
    filename = args[0]
    current_flows = args[1:]
    with open(filename, "r") as stream:
        try:
            struct = yaml.safe_load(stream)
            # Now call recursive fun
            if 'flows' in struct:
                array = recursive_key_search(struct['flows'], current_flows=current_flows)
                for i in array:
                    print(i)
        except yaml.YAMLError as exc:
            print(exc)


if __name__ == "__main__":
    main(sys.argv[1:])
