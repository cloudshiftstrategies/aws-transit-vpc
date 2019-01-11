import boto3, sys
from boto3.dynamodb.conditions import Key, Attr
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb=boto3.resource('dynamodb')


transitConfig = {}
subscriberConfig = {}

def fetchFromTransitConfigTable(transitConfigTable=None):
    """Get the data from TransitConfig table and returns it as dictionary
    """
    try:
        table = dynamodb.Table(transitConfigTable)
        response=table.scan()
        for item in response['Items']:
            transitConfig[item['Property']]=item['Value']
        return transitConfig
    except Exception as e:
        logger.info("Fetching From Config talbe is Failed, Error: {}".format(str(e)))
        return False
def fetchFromSubscriberConfigTable(subscriberConfigTable=None):
    """Get the data from SubscriberConfig table and retruns it as dictionary
    """
    try:
        table = dynamodb.Table(subscriberConfigTable)
        response=table.scan()
        for item in response['Items']:
            subscriberConfig[item['Property']]=item['Value']
        return subscriberConfig
    except Exception as e:
        logger.info("Fetching From Config talbe is Failed, Error: {}".format(str(e)))
        return False
def sendToQueue(sqsQueueUrl,messageBody,messageGroupId):
    """Sends message to the SQS Queue
    """
    try:
        sqsConnection=boto3.client('sqs',region_name=sqsQueueUrl.split('.')[1])
        sqsConnection.send_message(QueueUrl=sqsQueueUrl,MessageBody=messageBody,MessageGroupId=messageGroupId)
        return True
    except Exception as e:
        logger.error("Error in sendToQueue(), Error: {}".format(str(e)))
        #return False

def publishToSns(snsTopicArn, message, roleArn=None):
    """Publish message to SNS Topic
    """
    try:
        snsConnection=boto3.client('sns',region_name=snsTopicArn.split(':')[3])
        if roleArn:
            stsConnection = boto3.client('sts')
            assumedrole = stsConnection.assume_role(RoleArn=roleArn, RoleSessionName="Sample")
            snsConn = boto3.client('sns',region_name=snsTopicArn.split(':')[3], aws_access_key_id=assumedrole['Credentials']['AccessKeyId'], aws_secret_access_key=assumedrole['Credentials']['SecretAccessKey'], aws_session_token=assumedrole['Credentials']['SessionToken'])
            snsConn.publish(TopicArn=snsTopicArn,Message=str(message))
            return True
        snsConnection.publish(TopicArn=snsTopicArn,Message=str(message))
        return True
    except Exception as e:
        logger.error("Error in publishToSns(), Error: {}".format(str(e)))
        #return False
		
def fetchFromQueue(sqsQueueUrl):
    """Get one message from SQS Queue and return it
    """
    try:
        sqsConnection=boto3.client('sqs',region_name=sqsQueueUrl.split('.')[1])
        receive_message=sqsConnection.receive_message(QueueUrl=sqsQueueUrl,MaxNumberOfMessages=1)
        if receive_message:
            if 'Messages' in receive_message:
                #Delete Message from Queue
                print("Deleting message from {} Queue-> {}".format(sqsQueueUrl,receive_message['Messages'][0]['Body']))
                sqsConnection.delete_message(QueueUrl=sqsQueueUrl,ReceiptHandle=receive_message['Messages'][0]['ReceiptHandle'])
                return receive_message
    except Exception as e:
        logger.error("Fetching from {} Queue is Failed, Error {}".format(sqsQueueUrl,str(e)))
        #return False

def deleteVgw(vgwId,vpcId,awsRegion):
    """Detache and Deletes the VGW from VPC
    """
    try:
        ec2_conn =boto3.client('ec2',region_name=awsRegion)
        response = ec2_conn.describe_vpn_gateways(VpnGatewayIds=[vgwId])['VpnGateways']
        if response:
            ec2_conn.detach_vpn_gateway(VpnGatewayId=vgwId, VpcId=vpcId)
            logger.info("Detached VGW: {} from Vpc: {}".format(vgwId,vpcId))
            ec2_conn.delete_vpn_gateway(VpnGatewayId=vgwId)
            logger.info("Deleted VGW: {}".format(vgwId))
            return response[0]['AmazonSideAsn']
    except Exception as e:
        logger.error("Error in deleteVgw(), Error: {}".format(str(e)))
        pass

def isVgwAttachedToVpc(vpcId,awsRegion):
    """Verifies whether the VPC has any VGW attached, return either VgwId or False
    """
    try:
        ec2_conn = boto3.client('ec2', region_name=awsRegion)
        filters = [{'Name':'attachment.vpc-id','Values':[vpcId]}, {'Name':'attachment.state','Values':['attached']}]
        response = ec2_conn.describe_vpn_gateways(Filters=filters)['VpnGateways']
        if response: return response[0]
        else: return False
    except Exception as e:
        logger.error("Error in isVgwAttachedToVpc(), Error: {}".format(str(e)))
        return False
def checkCgw(awsRegion, n1Eip, n2Eip):
    """Verifies whether the CGWs are already created or not, returns either a list of cgwIds or False
    """
    try:
        cgwIds = []
        ec2_conn = boto3.client('ec2', region_name=awsRegion)
        filters = [{'Name':'ip-address','Values':[n1Eip]}]
        response = ec2_conn.describe_customer_gateways(Filters=filters)['CustomerGateways']
        if response:
            for cgw in response:
                if cgw['State']=='available':
                    cgwIds.append(cgw['CustomerGatewayId'])
        filters = [{'Name':'ip-address','Values':[n2Eip]}]
        response = ec2_conn.describe_customer_gateways(Filters=filters)['CustomerGateways']
        if response:
            for cgw in response:
                if cgw['State']=='available':
                    cgwIds.append(cgw['CustomerGatewayId'])
        if cgwIds:
            return cgwIds
        else:
            return False
    except Exception as e:
        logger.error("Error from checkCgw, Error: {}".format(str(e)))
        return False

def createVgwAttachToVpc(vpcId,vgwAsn,region,paGroup):
    """Creates a VGW and attach it to the VPC, returns VgwId
    """
    try:
        tags=[{'Key':'Name','Value':paGroup}]
        import time
        ec2Connection=boto3.client('ec2',region_name=region)
        #Create VGW with vgwAsn
        response=ec2Connection.create_vpn_gateway(Type='ipsec.1',AmazonSideAsn=int(vgwAsn))
        #Attach VGW to VPC
        while True:
            status=ec2Connection.attach_vpn_gateway(VpcId=vpcId,VpnGatewayId=response['VpnGateway']['VpnGatewayId'],DryRun=False)['VpcAttachment']
            if status['State']=='attaching':
                time.sleep(2)
            elif status['State']=='attached':
                ec2Connection.create_tags(Resources=[response['VpnGateway']['VpnGatewayId']],Tags=tags)
                return response['VpnGateway']['VpnGatewayId']
            else:
                return None
        #return response['VpnGateway']['VpnGatewayId']
    except Exception as e:
        logger.error("Error creating Vgw and Attaching it to VPC, Error : {}".format(str(e)))
        return False

def createCgw(cgwIp,cgwAsn,region,tag):
    """Creates CGW and returns CgwId
    """
    try: 
        tags=[{'Key':'Name','Value':tag}]
        ec2Connection=boto3.client('ec2',region_name=region)
        response=ec2Connection.create_customer_gateway(BgpAsn=int(cgwAsn), PublicIp=cgwIp, Type='ipsec.1')
        ec2Connection.create_tags(Resources=[response['CustomerGateway']['CustomerGatewayId']],Tags=tags)
        return response['CustomerGateway']['CustomerGatewayId']
    except Exception as e:
        logger.error("Error in createCgw(), Error: {}".format(str(e)))
        return False
def uploadObjectToS3(vpnConfiguration, bucketName,assumeRoleArn=None):
    """Uploads an object(VPN Conf file) to S3 bucket
    """
    try:
        s3Connection=boto3.resource('s3')
        fileName=vpnConfiguration['VpnConnection']['VpnConnectionId']+'.xml'
        vpnConfig=vpnConfiguration['VpnConnection']['CustomerGatewayConfiguration']
        #open(filePath).write(vpnConfiguration['VpnConnection']['CustomerGatewayConfiguration'])
        if assumeRoleArn:
            stsConnection = boto3.client('sts')
            assumedrole = stsConnection.assume_role(RoleArn=assumeRoleArn, RoleSessionName="Sample")
            s3 = boto3.resource('s3', aws_access_key_id=assumedrole['Credentials']['AccessKeyId'], aws_secret_access_key=assumedrole['Credentials']['SecretAccessKey'], aws_session_token=assumedrole['Credentials']['SessionToken'])    
            s3.Object(bucketName, fileName).put(Body=vpnConfig)
            return True
        s3Connection.Object(bucketName, fileName).put(Body=vpnConfig)
        return True
    except Exception as e:
        logger.error("Error uploading file to S3 Bucket, Error : %s"%str(e))
        return False
		
def getVpnConfFromS3(vpnId,region,bucketName):
    """Downloads the VPN configuration file from S3 bucket
    """
    try:
        s3Connection=boto3.resource('s3')
        fileName=vpnId+'.xml'
        vpnConfiguration=s3Connection.Object(bucketName, fileName).get()['Body'].read().decode('utf-8')
        #Return the XML configuration of VPN Connection
        return vpnConfiguration 
    except Exception as e:
        logger.error("Object Download Failed, Error : {}".format(str(e)))
        return False
	
def createVpnConnectionUploadToS3(region,vgwId,cgwId,tunnelOneCidr,tunnelTwoCidr,tag,bucketName,assumeRoleArn=None):
    """Creates VPN connection and upload the VPN configuration to the S3 bucket
    """
    try:
        tags=[{'Key':'Name','Value':tag}]
        ec2Connection=boto3.client('ec2',region_name=region)
        response=ec2Connection.create_vpn_connection(
            CustomerGatewayId=cgwId,
            Type='ipsec.1',
            VpnGatewayId=vgwId,
            DryRun=False,
            Options={
                'StaticRoutesOnly': False,
                'TunnelOptions': [
                    {
                        'TunnelInsideCidr': tunnelOneCidr
                    },
                    {
                        'TunnelInsideCidr': tunnelTwoCidr
                    }
                ]
            }
        )
        ec2Connection.create_tags(Resources=[response['VpnConnection']['VpnConnectionId']],Tags=tags)
        #Uploading VPN configuration to S3 bucket
        if assumeRoleArn:
            uploadObjectToS3(response,bucketName,assumeRoleArn)
        else:
            uploadObjectToS3(response,bucketName)
        return response['VpnConnection']['VpnConnectionId']
    except Exception as e:
        logger.error("Error Creating VPN Connection, Error: {}".format(str(e)))
