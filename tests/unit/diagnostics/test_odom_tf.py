from robobench.diagnostics.odom_tf import odom_to_tf


def test_odom_to_tf_copies_pose_and_frames():
    tf = odom_to_tf(
        frame_id="odom",
        child_frame_id="base_link",
        stamp_sec=10,
        stamp_nanosec=500,
        position=(1.0, 2.0, 0.0),
        orientation=(0.0, 0.0, 0.7071, 0.7071),
    )
    assert tf.frame_id == "odom"
    assert tf.child_frame_id == "base_link"
    assert (tf.stamp_sec, tf.stamp_nanosec) == (10, 500)
    assert (tf.tx, tf.ty, tf.tz) == (1.0, 2.0, 0.0)
    assert (tf.qx, tf.qy, tf.qz, tf.qw) == (0.0, 0.0, 0.7071, 0.7071)


def test_odom_topic_for_namespace():
    from robobench.diagnostics.odom_tf import odom_topic

    assert odom_topic("turtlebot468") == "/turtlebot468/odom"
    assert odom_topic("/turtlebot468/") == "/turtlebot468/odom"
    assert odom_topic("") == "/odom"
