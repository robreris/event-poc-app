#!/usr/bin/env python3
import argparse, time, sys
import boto3
from botocore.exceptions import ClientError

def wait_instance_ok(ec2, instance_id):
    print("Waiting for EC2 status checks...", flush=True)
    ec2.get_waiter("instance_status_ok").wait(InstanceIds=[instance_id])
    print("EC2 checks passed.")

def wait_ssm_online(ssm, instance_id, timeout=900, poll=10):
    print("Waiting for SSM Online...", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        resp = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
        )
        info = resp.get("InstanceInformationList", [])
        if info and info[0].get("PingStatus") == "Online":
            print("SSM Online.")
            return
        time.sleep(poll)
    raise TimeoutError("SSM agent not online in time")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", required=True)
    p.add_argument("--instance-id", required=True)
    p.add_argument("--param-prefix", required=True, help="e.g., /app or /env/prod/render")
    p.add_argument("--python-win", required=True, help="Path to python.exe on the Windows instance")
    p.add_argument("--script-directory", required=True, help="Folder containing agent-script.py on the instance")
    p.add_argument("--script-exe", required=True, default="agent-script.py", help="Python script to execute powerpoint functions.")
    p.add_argument("--stop-after", action="store_true", help="Stop instance after run")
    args = p.parse_args()

    ec2 = boto3.client("ec2", region_name=args.region)
    ssm = boto3.client("ssm", region_name=args.region)

    # 1) Start instance if stopped
    desc = ec2.describe_instances(InstanceIds=[args.instance_id])
    state = desc["Reservations"][0]["Instances"][0]["State"]["Name"]
    if state in ("stopped", "stopping"):
        print(f"Starting instance {args.instance_id} (state={state})...")
        ec2.start_instances(InstanceIds=[args.instance_id])
    else:
        print(f"Instance {args.instance_id} already {state}.")

    # 2) Wait for instance & SSM
    wait_instance_ok(ec2, args.instance_id)
    wait_ssm_online(ssm, args.instance_id)

    # 3) Build PowerShell command that:
    #    - fetches three SecureString params from SSM Parameter Store
    #    - exports them as env vars
    #    - runs the Python script on Windows
    param_dns  = f"{args.param_prefix}/rabbithost"
    param_user = f"{args.param_prefix}/rabbitusername"
    param_pass = f"{args.param_prefix}/rabbitpassword"

    commands = [
        f'$python  = "{args.python_win}"',
        f'$script  = "{args.script_directory}{args.script_exe}"',
        f'$work    = "{args.script_directory}"',
        f'$logOut  = "{args.script_directory}agent.out.log"',
        f'$logErr  = "{args.script_directory}agent.err.log"',
        f'$pidFile = "{args.script_directory}agent.pid"',
        # Pull secure params (requires aws cli on instance; standard on AWS Windows AMIs)
        f'$env:RABBITMQ_HOST = (aws ssm get-parameter --name "{param_dns}"  --with-decryption --query "Parameter.Value" --output text)',
        f'$env:RABBITMQ_USER = (aws ssm get-parameter --name "{param_user}" --with-decryption --query "Parameter.Value" --output text)',
        f'$env:RABBITMQ_PASS = (aws ssm get-parameter --name "{param_pass}" --with-decryption --query "Parameter.Value" --output text)',
        # (Optional) Set-Location if your script uses relative paths
        # "Set-Location 'C:\\render-agent'",
        '& $python $script rabbitmq'
        #'if (Test-Path $pidFile) { try { Stop-Process -Id (Get-Content $pidFile) -Force -ErrorAction Stop } catch {} ; Remove-Item $pidFile -ErrorAction SilentlyContinue }',
        #'$ps = Start-Process -FilePath $python -ArgumentList "`"$script`"", "rabbitmq" -WorkingDirectory $work -NoNewWindow -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru',
        #'$ps.Id | Out-File -FilePath $pidFile -Encoding ascii -Force'
    ]

    print("Sending SSM Run Command...", flush=True)
    print(f'Running commands: {commands}')
    resp = ssm.send_command(
        InstanceIds=[args.instance_id],
        DocumentName="AWS-RunPowerShellScript",
        Parameters={"commands": commands},
        CloudWatchOutputConfig={
            "CloudWatchLogGroupName": "/ec2/ssm/render-agent",
            "CloudWatchOutputEnabled": True
        }
    )
    cmd_id = resp["Command"]["CommandId"]
    print(f"CommandId: {cmd_id}")

    deadline = time.time() + 600  # 10 min overall safety timeout
    sleep = 2

    # 4) Wait for completion and print summary
    while True:
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=args.instance_id)
            status = inv["Status"]
            if status in ("Success", "Failed", "Cancelled", "TimedOut"):
                print(f"Final status: {status}")
                # Show a snippet in stdout; full logs in CloudWatch if enabled
                out = inv.get("StandardOutputContent", "")
                err = inv.get("StandardErrorContent", "")
                if out:
                    print("---- STDOUT (truncated) ----")
                    print(out[:4000])
                if err:
                    print("---- STDERR (truncated) ----", file=sys.stderr)
                    print(err[:4000], file=sys.stderr)
                break
            time.sleep(5)
            continue
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("InvocationDoesNotExist", "ThrottlingException"):
                if time.time() > deadline:
                    raise
                time.sleep(sleep)
                # gentle backoff, cap at ~10s
                sleep = min(sleep + 1, 10)
                continue
            # Something else—bubble up
            raise

    # 5) Optional: stop instance
    if args.stop_after:
        print("Stopping instance...")
        ec2.stop_instances(InstanceIds=[args.instance_id])

if __name__ == "__main__":
    main()

