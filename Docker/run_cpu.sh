xhost +local:root

docker run -it \
	--workdir="/home" \
	--env="DISPLAY" \
	--env="QT_X11_NO_MITSHM=1" \
	--volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" \
	--volume="/home/$USER/Studia/Sem2/ARL/shared:/home/shared:rw" \
	--privileged \
	--network=host \
	--name="TELLO_ROS" \
	tello_ros\
	/bin/bash
